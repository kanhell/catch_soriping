# 캐치 소리핑 (Catch Soriping)

라즈베리파이가 아파트 안내방송 소리를 감지 → 녹음 → 텍스트 변환(STT) → 카테고리 자동 분류 →
Firebase 업로드 → LED로 알림까지 자동으로 처리하는 시스템입니다.
와이파이가 없는 환경에서는 블루투스(폰 앱)로 와이파이 정보를 받아 자동 연결합니다.

## 폴더 구성 (모두 `/home/ask/catch_soriping/` 안에 위치)

| 파일 | 역할 |
|---|---|
| `main.py` | 전체 파이프라인 실행 (녹음→STT→분류→업로드→LED). **부팅 시 자동 실행됨** |
| `recorder.py` | 소리 감지 시 자동 녹음, `main.py`가 import해서 사용 |
| `stt_function.py` | STT 변환, 카테고리 분류, 제목 생성, Firebase 업로드 로직 |
| `led_notify.py` | 온보드 LED(ACT/PWR) 알림 제어 |
| `bt_wifi_setup.py` | 안드로이드용 Classic Bluetooth(SPP) 와이파이 프로비저닝 서버 |
| `bt_agent.py` | 확인 버튼 없이 자동으로 페어링 승인해주는 에이전트 (SPP용) |
| `ble_wifi_gatt_server.py` | iOS/안드로이드 공용 BLE 와이파이 프로비저닝 서버 |
| `logger_setup.py` | 모든 스크립트가 공용으로 쓰는 로거 설정 |
| `logs/` | 각 스크립트의 로그 파일이 자동 생성되는 폴더 |

시스템 경로에 설치되는 것들:

| 파일 | 위치 |
|---|---|
| `bt-discoverable.sh` | `/usr/local/bin/bt-discoverable.sh` |
| `led-setup.sh` | `/usr/local/bin/led-setup.sh` |
| `start_main.sh` | `/usr/local/bin/start_main.sh` |
| `bt-wifi-setup.service` | `/etc/systemd/system/` |
| `bt-agent.service` | `/etc/systemd/system/` |
| `ble-wifi-setup.service` | `/etc/systemd/system/` |
| `led-setup.service` | `/etc/systemd/system/` |
| `soriping-main.service` | `/etc/systemd/system/` |

---

## 전체 동작 흐름

1. 부팅되면 블루투스(SPP)와 BLE 서버가 즉시 켜짐 (와이파이 상태와 무관하게 항상 대기)
2. `soriping-main.service`가 와이파이 연결 여부를 5초마다 확인
   - 이미 연결되어 있으면 → 바로 `main.py` 실행
   - 연결 안 되어 있으면 → 계속 대기. 그 사이 폰이 블루투스나 BLE로 와이파이 정보를 보내면 자동 연결
3. 와이파이가 연결되는 순간 `main.py`가 실행되어 소리 감지(녹음) 시작
4. 소리가 감지되면 녹음 → STT 변환 → 카테고리 자동 분류(점검/화재/긴급/안내) → 제목 생성 → Firebase 업로드
5. 업로드 성공 시 카테고리에 맞는 LED 알림 시작 (Firestore에서 `isRead`가 `true`가 되면 즉시 꺼짐)

---

## 최초 설치

### 1. 패키지 설치
```bash
sudo apt update
sudo apt install -y bluetooth bluez libbluetooth-dev python3-dbus python3-gi portaudio19-dev

pip install sounddevice soundfile numpy --break-system-packages
pip install pybluez2 --break-system-packages
pip install faster-whisper firebase-admin --break-system-packages
```

### 2. 파일 배치
- 위 표의 `.py` 파일들을 모두 `/home/ask/catch_soriping/`에 배치
- Firebase 서비스 계정 키(JSON)도 같은 폴더에 넣고, `main.py`의 `FIREBASE_KEY_PATH`가 그 파일명과 일치하는지 확인

### 3. 블루투스/LED 초기 설정 (최초 1회, 터미널에서 직접 실행)
```bash
echo none | sudo tee /sys/class/leds/ACT/trigger
echo none | sudo tee /sys/class/leds/PWR/trigger
```

### 4. 시스템 스크립트/서비스 등록
```bash
# 스크립트 배치
sudo cp bt-discoverable.sh /usr/local/bin/bt-discoverable.sh
sudo cp led-setup.sh /usr/local/bin/led-setup.sh
sudo cp start_main.sh /usr/local/bin/start_main.sh
sudo chmod +x /usr/local/bin/bt-discoverable.sh /usr/local/bin/led-setup.sh /usr/local/bin/start_main.sh

# 서비스 배치
sudo cp bt-wifi-setup.service /etc/systemd/system/
sudo cp bt-agent.service /etc/systemd/system/
sudo cp ble-wifi-setup.service /etc/systemd/system/
sudo cp led-setup.service /etc/systemd/system/
sudo cp soriping-main.service /etc/systemd/system/

# 등록 및 실행
sudo systemctl daemon-reload
sudo systemctl enable --now bt-agent.service
sudo systemctl enable --now bt-wifi-setup.service
sudo systemctl enable --now ble-wifi-setup.service
sudo systemctl enable --now led-setup.service
sudo systemctl enable --now soriping-main.service
```

### 5. 일반 사용자 권한으로 LED 쓰기 (udev, 안 되면 systemd 서비스로 대체됨)
```bash
sudo nano /etc/udev/rules.d/99-leds.rules
```
```
SUBSYSTEM=="leds", ACTION=="add", RUN+="/bin/chmod 666 /sys/class/leds/%k/brightness"
```
```bash
sudo udevadm control --reload-rules
sudo udevadm trigger --action=add
```
(이 방법이 안 먹히면 `led-setup.service`가 부팅마다 `chmod`로 강제 적용해주니 그걸로 충분합니다.)

---

## 로그 확인 방법

모든 스크립트가 통일된 형식(`시간 [레벨] 이름: 메시지`)으로 로그를 남깁니다. 두 가지 방법으로 볼 수 있습니다.

### 방법 1: systemd 서비스 로그 (실시간)
```bash
sudo journalctl -u soriping-main.service -f      # main.py 로그
sudo journalctl -u bt-wifi-setup.service -f      # 블루투스(SPP) 로그
sudo journalctl -u bt-agent.service -f           # 자동 페어링 로그
sudo journalctl -u ble-wifi-setup.service -f     # BLE 로그
```

### 방법 2: 로그 파일 (누적 기록, 재부팅해도 남음)
```bash
cat /home/ask/catch_soriping/logs/main.log
cat /home/ask/catch_soriping/logs/recorder.log
cat /home/ask/catch_soriping/logs/stt_function.log
cat /home/ask/catch_soriping/logs/led_notify.log
cat /home/ask/catch_soriping/logs/bt_wifi_setup.log
cat /home/ask/catch_soriping/logs/bt_agent.log
cat /home/ask/catch_soriping/logs/ble_wifi_gatt_server.log
```
파일 하나당 최대 2MB까지 쌓이고, 넘으면 자동으로 이전 로그(최대 3개)를 남기고 정리됩니다.

---

## 블루투스/BLE 통신 규격 (폰 앱 개발 시 참고)

두 방식 모두 **요청/응답 JSON 형식은 동일**합니다.

**요청 (폰 → 파이)**
```json
{"ssid": "와이파이이름", "password": "비밀번호"}
```

**응답 (파이 → 폰)**
```json
{"status": "ok", "message": "연결 성공"}
```
또는
```json
{"status": "error", "message": "구체적인 오류 내용"}
```

### 안드로이드: Classic Bluetooth (SPP)
- Service UUID: `00001101-0000-1000-8000-00805F9B34FB`
- 서비스 이름: `RaspberryPi-WiFiSetup`
- 시스템 블루투스 설정에서 검색/페어링 가능
- 메시지는 UTF-8, 줄바꿈(`\n`)으로 종료

### iOS / 안드로이드 공용: BLE (GATT)
- Service UUID: `12345678-1234-5678-1234-56789abcdef0`
- Config 특성 (Write, 폰→파이): `12345678-1234-5678-1234-56789abcdef1`
- Result 특성 (Notify/Read, 파이→폰): `12345678-1234-5678-1234-56789abcdef2`
- 로컬 이름: `RaspberryPi-WiFiSetup`
- **시스템 블루투스 설정에서는 안 보임** — 반드시 전용 앱(`CoreBluetooth`/`BluetoothLeScanner`)으로 스캔·연결해야 함

---

## LED 알림 규칙

| 카테고리 | LED | 속도 | 최대 지속 시간 |
|---|---|---|---|
| 안내(general) / 점검(maintenance) | 초록(ACT) | 느리게 (1초 켜짐/1초 꺼짐) | 최대 1분 |
| 긴급(emergency) / 화재(fire) | 빨강(PWR) | 빠르게 (0.15초 켜짐/꺼짐) | 최대 3분 |

Firestore에서 해당 공지의 `isRead`가 `true`로 바뀌는 순간 실시간으로 감지되어 LED가 즉시 꺼집니다.

---

## 자주 겪은 문제 & 해결 방법

| 증상 | 원인 / 해결 |
|---|---|
| `nmcli radio wifi` → `disabled` | `sudo rfkill unblock wifi` 또는 `nmcli radio wifi on` |
| `Not authorized to perform this operation` | `sudo`를 붙여서 실행 |
| `input overflow` 경고 (recorder.py) | `BLOCK_DURATION` 값을 늘려서 완화 (현재 0.5초로 설정됨) |
| BT 페어링 시 파이에서 확인 버튼을 눌러야 함 | `bt_agent.py`(`bt-agent.service`)가 자동 승인 처리 |
| LED 파일 권한 오류 (`Permission denied`) | `led-setup.service`가 부팅 시 자동으로 `chmod 666` 적용 |
| `ModuleNotFoundError` | 해당 패키지를 `pip install ... --break-system-packages`로 설치 |
| VS Code에서 시스템 폴더(`/usr/local/bin`, `/etc/systemd/system`)에 저장 시 `EACCES` | 홈 폴더에 저장 후 터미널에서 `sudo cp`로 이동 |

---

## 서비스 전체 상태 한 번에 확인

```bash
sudo systemctl status bt-agent.service bt-wifi-setup.service ble-wifi-setup.service led-setup.service soriping-main.service
```
모두 `active (running)` 또는 `active (exited)`(led-setup은 1회성이라 exited가 정상)면 정상입니다.

## 재부팅 테스트
```bash
sudo reboot
```
재부팅 후 위 상태 확인 명령과 `sudo journalctl -u soriping-main.service -f`로 자동 실행이 잘 되는지 확인하세요.
