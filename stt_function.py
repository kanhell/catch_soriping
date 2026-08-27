# -*- coding: utf-8 -*-
"""
캐치 소리핑 (Catch Soriping) - STT + 자동 분류 + Firebase 업로드

main.py에서 import해서 사용하는 모듈. 단독 실행용 코드는 없음(README 참고).
"""

import os
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"

from faster_whisper import WhisperModel
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime, timezone

from logger_setup import get_logger

logger = get_logger("stt_function")


# ============================================================
# 1. STT 엔진
# ============================================================

class STTEngine:
    def __init__(self, model_size: str = "small", device: str = "cpu"):
        compute_type = "int8" if device == "cpu" else "float16"
        self.model = WhisperModel(model_size, device=device, compute_type=compute_type)

    def transcribe(self, audio_path: str, language: str = "ko") -> dict:
        if not os.path.exists(audio_path):
            raise FileNotFoundError(f"오디오 파일이 없습니다: {audio_path}")

        segments, info = self.model.transcribe(
            audio_path,
            language=language,
            beam_size=5,
            vad_filter=True,
        )

        segment_list = []
        full_text = []

        for seg in segments:
            text = seg.text.strip()
            if text:
                full_text.append(text)
                segment_list.append({
                    "start": round(seg.start, 2),
                    "end": round(seg.end, 2),
                    "text": text,
                })

        return {
            "text": " ".join(full_text),
            "segments": segment_list,
            "duration": info.duration,
        }


# ============================================================
# 2. 방송 카테고리 자동 분류
# ============================================================

class CategoryClassifier:
    """STT 결과를 분석해서 점검 / 화재 / 긴급 / 안내로 자동 분류"""

    FIRE_KEYWORDS = [
        "화재", "불이 났", "불이났", "불이 발생", "연기가 발생",
        "연기 발생", "화재 발생", "소방", "발화", "화재경보", "화재 경보",
    ]

    EMERGENCY_KEYWORDS = [
        "긴급", "대피", "즉시 대피", "사고", "위험", "침수",
        "가스 누출", "가스누출", "폭발", "출입 금지", "사용 금지",
        "접근 금지", "즉시",
    ]

    MAINTENANCE_KEYWORDS = [
        "점검", "정기점검", "정기 점검", "보수", "수리", "공사", "교체",
        "정비", "시설 점검", "승강기 점검", "엘리베이터 점검", "소방 점검",
        "전기 점검", "배관 점검", "청소",
    ]

    def classify(self, text: str) -> str:
        text = text.strip()

        for keyword in self.FIRE_KEYWORDS:
            if keyword in text:
                return "fire"

        for keyword in self.EMERGENCY_KEYWORDS:
            if keyword in text:
                return "emergency"

        for keyword in self.MAINTENANCE_KEYWORDS:
            if keyword in text:
                return "maintenance"

        return "general"


# ============================================================
# 3. 제목 생성
# ============================================================

class TitleGenerator:
    """카테고리 태그만 표시: [점검] [화재] [긴급] [안내]"""

    CATEGORY_TAG = {
        "maintenance": "[점검]",
        "fire": "[화재]",
        "emergency": "[긴급]",
        "general": "[안내]",
    }

    def generate(self, category: str = "general") -> str:
        return self.CATEGORY_TAG.get(category, "[안내]")


# ============================================================
# 4. Firebase 업로더
# ============================================================

class FirebaseUploader:
    def __init__(self, key_path: str):
        if not firebase_admin._apps:
            cred = credentials.Certificate(key_path)
            firebase_admin.initialize_app(cred)
        self.db = firestore.client()

    def upload_announcement(self, title: str, content: str, category: str = "general") -> str:
        doc_ref = self.db.collection("announcements").document()
        doc_ref.set({
            "title": title,
            "text": content,
            "timestamp": datetime.now(timezone.utc),
            "category": category,
            "isRead": False,
        })
        logger.info(f"업로드 완료 (id={doc_ref.id}, 제목={title}, 카테고리={category})")
        return doc_ref.id


# ============================================================
# 5. STT → 분류 → 제목 생성 → Firebase 업로드 (일괄 처리 헬퍼)
# ============================================================

def process_and_upload(stt_engine, classifier, title_generator, uploader, audio_path: str):
    """
    STT 변환 -> 분류 -> 제목 생성 -> Firebase 업로드까지 처리한다.
    반환값: (doc_id, category). 업로드하지 않은 경우 (None, None).
    """
    logger.info(f"처리 중인 파일: {audio_path}")

    result = stt_engine.transcribe(audio_path)
    content = result["text"]
    logger.info(f"STT 변환 결과: {content}")

    if not content.strip():
        logger.info("인식된 텍스트가 없습니다. 업로드를 건너뜁니다.")
        return None, None

    category = classifier.classify(content)
    title = title_generator.generate(category)
    logger.info(f"자동 분류: {category} / 제목: {title}")

    doc_id = uploader.upload_announcement(title=title, content=content, category=category)
    return doc_id, category
