#!/usr/bin/env python3
"""
라즈베리파이 5 온보드 LED 알림 모듈
사용법/설정은 README.md 참고.
"""

import threading
import time

from logger_setup import get_logger

logger = get_logger("led_notify")

GREEN_LED_PATH = "/sys/class/leds/ACT/brightness"
RED_LED_PATH = "/sys/class/leds/PWR/brightness"

# 카테고리별 설정: (LED 경로, 켜짐 시간, 꺼짐 시간, 최대 지속 시간(초))
CATEGORY_LED_CONFIG = {
    "general":     (GREEN_LED_PATH, 1.0, 1.0, 60),
    "maintenance": (GREEN_LED_PATH, 1.0, 1.0, 60),
    "emergency":   (RED_LED_PATH, 0.15, 0.15, 180),
    "fire":        (RED_LED_PATH, 0.15, 0.15, 180),
}


def _set_led(led_path: str, value: int):
    try:
        with open(led_path, "w") as f:
            f.write(str(value))
    except PermissionError:
        logger.error(f"권한 오류: {led_path}에 쓸 수 없습니다.")
    except FileNotFoundError:
        logger.error(f"{led_path} 를 찾을 수 없습니다.")
    except Exception as e:
        logger.error(str(e))


def _blink_loop(led_path: str, on_time: float, off_time: float, max_duration: float, stop_event: threading.Event):
    start = time.time()
    while time.time() - start < max_duration:
        if stop_event.is_set():
            break
        _set_led(led_path, 1)
        if stop_event.wait(timeout=on_time):
            break
        _set_led(led_path, 0)
        if stop_event.wait(timeout=off_time):
            break
    _set_led(led_path, 0)


def notify_new_announcement(db, doc_id: str, category: str):
    """
    새 안내방송에 대해 카테고리에 맞는 LED를 켠다.
    Firestore의 announcements/{doc_id} 문서를 실시간으로 감시하다가
    isRead가 true가 되면 즉시 LED를 끈다.
    """
    led_path, on_time, off_time, max_duration = CATEGORY_LED_CONFIG.get(
        category, CATEGORY_LED_CONFIG["general"]
    )
    led_color = "초록(ACT)" if led_path == GREEN_LED_PATH else "빨강(PWR)"
    logger.info(f"LED 알림 시작 (doc_id={doc_id}, category={category}, LED={led_color}, 최대 {max_duration:.0f}초)")

    stop_event = threading.Event()
    doc_ref = db.collection("announcements").document(doc_id)

    def on_snapshot(doc_snapshot, changes, read_time):
        for doc in doc_snapshot:
            data = doc.to_dict() or {}
            if data.get("isRead") is True:
                logger.info(f"읽음 처리 감지 (doc_id={doc_id}) - LED 종료")
                stop_event.set()

    watch = doc_ref.on_snapshot(on_snapshot)

    def run():
        _blink_loop(led_path, on_time, off_time, max_duration, stop_event)
        watch.unsubscribe()
        if not stop_event.is_set():
            logger.info(f"LED 알림 최대 시간 도달로 종료 (doc_id={doc_id})")

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread
