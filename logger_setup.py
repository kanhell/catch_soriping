#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
캐치 소리핑 - 공용 로거 설정 모듈

모든 스크립트가 이 모듈의 get_logger()를 사용해 로그를 남긴다.
- 콘솔(터미널/journalctl)과 파일(logs/*.log)에 동시에 기록됨
- 로그 파일은 이 파일과 같은 폴더의 logs/ 하위에 스크립트 이름별로 생성됨
- 파일 하나당 최대 2MB, 최근 3개까지 보관(RotatingFileHandler)
"""

import logging
import os
from logging.handlers import RotatingFileHandler

LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
os.makedirs(LOG_DIR, exist_ok=True)

_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_DATEFMT = "%Y-%m-%d %H:%M:%S"


def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger  # 이미 설정된 로거면 그대로 반환 (중복 핸들러 방지)

    logger.setLevel(logging.INFO)
    formatter = logging.Formatter(_FORMAT, datefmt=_DATEFMT)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    file_path = os.path.join(LOG_DIR, f"{name}.log")
    file_handler = RotatingFileHandler(
        file_path, maxBytes=2 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    logger.propagate = False
    return logger
