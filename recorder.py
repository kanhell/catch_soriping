#!/usr/bin/env python3
"""
소리 감지 자동 녹음 스크립트
사용법/설정값 설명은 README.md 참고.
"""

import os
import time
import datetime
import numpy as np
import sounddevice as sd
import soundfile as sf

from logger_setup import get_logger

logger = get_logger("recorder")

# ===== 설정값 (환경에 맞게 조정, 자세한 설명은 README 참고) =====
SAMPLE_RATE = 44100
CHANNELS = 1
BLOCK_DURATION = 0.5
THRESHOLD = 0.02
SILENCE_DURATION = 2.0
MIN_RECORD_DURATION = 0.5
OUTPUT_DIR = "recordings"
DEVICE = None
# ======================================

BLOCK_SIZE = int(SAMPLE_RATE * BLOCK_DURATION)


def get_rms(audio_block: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(audio_block))))


def save_recording(frames: list, start_time: datetime.datetime):
    """녹음을 파일로 저장하고, 저장된 파일 경로를 반환한다. 저장하지 않으면 None."""
    if not frames:
        return None

    audio_data = np.concatenate(frames, axis=0)
    duration = len(audio_data) / SAMPLE_RATE

    if duration < MIN_RECORD_DURATION:
        logger.info(f"녹음이 너무 짧아({duration:.2f}s) 저장하지 않음")
        return None

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    filename = start_time.strftime("recording_%Y%m%d_%H%M%S.wav")
    filepath = os.path.join(OUTPUT_DIR, filename)

    sf.write(filepath, audio_data, SAMPLE_RATE)
    logger.info(f"저장됨: {filepath} ({duration:.2f}초)")
    return filepath


def main(on_saved=None):
    """
    소리 감지 → 녹음 → 저장을 반복 실행한다.
    on_saved: 녹음 파일이 저장될 때마다 호출되는 콜백 함수. 인자로 저장된 파일 경로(str)를 받는다.
    """
    logger.info("소리가 감지되면 자동으로 녹음을 시작합니다. (Ctrl+C로 종료)")
    logger.info(f"설정: 임계값={THRESHOLD}, 무음 종료 기준={SILENCE_DURATION}초")

    is_recording = False
    frames = []
    silence_start = None
    record_start_time = None

    def callback(indata, frame_count, time_info, status):
        nonlocal is_recording, frames, silence_start, record_start_time

        if status:
            logger.warning(str(status))

        volume = get_rms(indata)

        if volume >= THRESHOLD:
            if not is_recording:
                is_recording = True
                frames = []
                record_start_time = datetime.datetime.now()
                logger.info(f"녹음 시작 (음량: {volume:.4f})")
            silence_start = None
            frames.append(indata.copy())
        else:
            if is_recording:
                frames.append(indata.copy())
                if silence_start is None:
                    silence_start = time.time()
                elif time.time() - silence_start >= SILENCE_DURATION:
                    is_recording = False
                    filepath = save_recording(frames, record_start_time)
                    frames = []
                    silence_start = None
                    if filepath and on_saved:
                        try:
                            on_saved(filepath)
                        except Exception as e:
                            logger.error(f"콜백 오류: {e}")
                    logger.info("소리 감지 대기 중...")

    try:
        with sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            blocksize=BLOCK_SIZE,
            device=DEVICE,
            callback=callback,
        ):
            while True:
                time.sleep(0.1)
    except KeyboardInterrupt:
        logger.info("프로그램을 종료합니다.")
        if is_recording and frames:
            filepath = save_recording(frames, record_start_time)
            if filepath and on_saved:
                try:
                    on_saved(filepath)
                except Exception as e:
                    logger.error(f"콜백 오류: {e}")
    except Exception as e:
        logger.error(str(e))


if __name__ == "__main__":
    main()
