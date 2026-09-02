#!/bin/bash
# 데스크톱이 뜬 뒤 kiosk_app.py를 자동으로 실행하는 스크립트

# 데스크톱 환경이 완전히 뜰 때까지 잠시 대기
sleep 8

cd /home/ask/catch_soriping
export DISPLAY=:0
/usr/bin/python3 kiosk_app.py >> /home/ask/catch_soriping/logs/kiosk_app_stdout.log 2>&1
