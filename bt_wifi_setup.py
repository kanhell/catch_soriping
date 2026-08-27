#!/usr/bin/env python3
"""
Raspberry Pi 블루투스(Classic SPP) Wi-Fi 프로비저닝 서버 - 안드로이드용
사용법/설정은 README.md 참고.
"""

import bluetooth
import subprocess
import json

from logger_setup import get_logger

logger = get_logger("bt_wifi_setup")

SERVICE_NAME = "RaspberryPi-WiFiSetup"
UUID = "00001101-0000-1000-8000-00805F9B34FB"


def connect_wifi(ssid: str, password: str):
    try:
        result = subprocess.run(
            ["sudo", "nmcli", "device", "wifi", "connect", ssid, "password", password],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            return True, "연결 성공"
        return False, result.stderr.strip() or "연결 실패"
    except subprocess.TimeoutExpired:
        return False, "연결 시도 시간 초과"
    except Exception as e:
        return False, str(e)


def send_response(client_sock, status: str, message: str):
    payload = json.dumps({"status": status, "message": message}, ensure_ascii=False) + "\n"
    client_sock.send(payload.encode("utf-8"))


def process_message(client_sock, raw_message: str):
    raw_message = raw_message.strip()
    if not raw_message:
        return

    logger.info(f"수신: {raw_message}")

    try:
        info = json.loads(raw_message)
    except json.JSONDecodeError:
        send_response(client_sock, "error", "JSON 형식이 올바르지 않습니다.")
        return

    ssid = info.get("ssid")
    password = info.get("password", "")

    if not ssid:
        send_response(client_sock, "error", "ssid 값이 없습니다.")
        return

    ok, msg = connect_wifi(ssid, password)
    send_response(client_sock, "ok" if ok else "error", msg)


def handle_client(client_sock):
    buffer = b""
    while True:
        data = client_sock.recv(1024)
        if not data:
            break
        buffer += data
        while b"\n" in buffer:
            line, buffer = buffer.split(b"\n", 1)
            process_message(client_sock, line.decode("utf-8", errors="ignore"))


def start_server():
    server_sock = bluetooth.BluetoothSocket(bluetooth.RFCOMM)
    server_sock.bind(("", bluetooth.PORT_ANY))
    server_sock.listen(1)

    port = server_sock.getsockname()[1]

    bluetooth.advertise_service(
        server_sock,
        SERVICE_NAME,
        service_id=UUID,
        service_classes=[UUID, bluetooth.SERIAL_PORT_CLASS],
        profiles=[bluetooth.SERIAL_PORT_PROFILE],
    )

    logger.info(f"'{SERVICE_NAME}' 서비스 대기 중 (RFCOMM 채널 {port})")

    while True:
        logger.info("클라이언트(폰) 연결 대기...")
        client_sock, client_info = server_sock.accept()
        logger.info(f"연결됨: {client_info}")
        try:
            handle_client(client_sock)
        except Exception as e:
            logger.error(f"처리 중 오류: {e}")
        finally:
            client_sock.close()
            logger.info("연결 종료. 다시 대기합니다.")


if __name__ == "__main__":
    start_server()
