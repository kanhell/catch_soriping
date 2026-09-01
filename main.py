#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
캐치 소리핑 (Catch Soriping) - 메인 실행 스크립트
사용법/설정/전체 흐름 설명은 README.md 참고.
"""

import os

import recorder
import led_notify
from stt_function import STTEngine, CategoryClassifier, TitleGenerator, FirebaseUploader, process_and_upload
from logger_setup import get_logger
from config import FIREBASE_KEY_PATH

logger = get_logger("main")

# ===== 설정값 (환경에 맞게 조정, 자세한 설명은 README 참고) =====
STT_MODEL_SIZE = "small"
STT_DEVICE = "cpu"
# ======================================


def main():
    if not os.path.exists(FIREBASE_KEY_PATH):
        raise FileNotFoundError(
            f"Firebase 키 파일을 찾을 수 없습니다: {FIREBASE_KEY_PATH}\n"
            "FIREBASE_KEY_PATH 값을 실제 키 파일 위치로 수정해주세요."
        )

    logger.info("STT 엔진 로딩 중... (모델 크기에 따라 시간이 걸릴 수 있습니다)")
    stt_engine = STTEngine(model_size=STT_MODEL_SIZE, device=STT_DEVICE)
    classifier = CategoryClassifier()
    title_generator = TitleGenerator()

    logger.info("Firebase 연결 중...")
    uploader = FirebaseUploader(FIREBASE_KEY_PATH)

    logger.info("준비 완료. 녹음 대기를 시작합니다.")

    def on_recording_saved(filepath: str):
        try:
            doc_id, category = process_and_upload(
                stt_engine, classifier, title_generator, uploader, filepath
            )
            if doc_id:
                logger.info(f"공지 업로드됨 (id={doc_id}, category={category}) - LED 알림 시작")
                led_notify.notify_new_announcement(uploader.db, doc_id, category)
        except Exception as e:
            logger.error(f"{filepath} 처리 중 오류 발생: {e}")

    recorder.main(on_saved=on_recording_saved)


if __name__ == "__main__":
    main()
