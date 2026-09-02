# 캐치 소리핑 (Catch Soriping)

라즈베리파이가 아파트 안내방송 소리를 감지 → 녹음 → 텍스트 변환(STT) → 카테고리 자동 분류 →
Firebase 업로드 → LED로 알림까지 자동으로 처리하는 시스템입니다.
모니터에는 방송 목록과 기기 연결(와이파이) 설정을 볼 수 있는 터치 UI가 뜨고,
와이파이가 없는 환경에서는 블루투스/BLE로 폰에서 와이파이 정보를 받아 자동 연결합니다.

## 폴더 구성 (모두 `/home/ask/catch_soriping/` 안에 위치)

### 핵심 실행 파일

| 파일 | 역할 |
|---|---|
| `main.py` | 전체 파이프라인 실행 (Firebase 연결 → STT 로딩 → 녹음 감지 → 분류·업로드 → LED). **부팅 시 자동 실행됨** |
| `recorder.py` | 소리 감지 시 자동 녹음, `main.py`가 import해서 사용 |
| `stt_function.py` | STT 변환, 카테고리 분류, 제목 생성, Firebase 업로드 로직 |
| `led_notify.py` | 온보드 LED(ACT/PWR) 알림 제어. Firestore의 `isRead`를 실시간 감시해 읽으면 즉시 소등 |
| `kiosk_app.py` | 모니터에 띄우는 Tkinter GUI (방송 목록 + 기기 연결 설정). **부팅 시 자동 실행됨** |
| `config.py` | 여러 파일이 공유하는 설정값 (Firebase 키 경로 등) |
| `logger_setup.py` | 모든 스크립트가 공용으로 쓰는 로거 설정 |
| `logs/` | 각 스크립트의 로그 파일이 자동 생성되는 폴더 |
| `recordings/` | 녹음된 WAV 파일이 저장되는 폴더 |

### 와이파이 자동 연결(블루투스/BLE 프로비저닝) 파일

| 파일 | 역할 |
|---|---|
| `bt_wifi_setup.py` | 안드로이드용 Classic Bluetooth(SPP) 와이파이 프로비저닝 서버 |
| `bt_agent.py` | 확인 버튼 없이 자동으로 페어링 승인해주는 에이전트 (SPP용) |
| `ble_wifi_gatt_server.py` | iOS/안드로이드 공용 BLE 와이파이 프로비저닝 서버 |

### 시스템 경로에 설치되는 것들

| 파일 | 위치 |
|---|---|
| `bt-discoverable.sh`, `led-setup.sh`, `start_main.sh`, `start_kiosk.sh` | `/usr/local/bin/` |
| `bt-wifi-setup.service`, `bt-agent.service`, `ble-wifi-setup.service`, `led-setup.service`, `soriping-main.service` | `/etc/systemd/system/` |
| `kiosk-ui.desktop` | `~/.config/autostart/` |

---

## 전체 동작 흐름

1. 부팅되면 블루투스(SPP)와 BLE 서버가 즉시 켜짐 (와이파이 상태와 무관하게 항상 대기)
2. `soriping-main.service`가 와이파이 연결 여부를 5초마다 확인
   - 이미 연결되어 있으면 → 바로 `main.py` 실행
   - 연결 안 되어 있으면 → 계속 대기. 그 사이 폰이 블루투스나 BLE로 와이파이 정보를 보내면 자동 연결
3. 와이파이가 연결되는 순간 `main.py`가 실행됨
   - Firebase에 연결하고 `system_status/recorder` 문서에 `"loading"` 상태를 기록
   - STT 엔진(faster-whisper) 로딩 완료 후 `"ready"` 상태로 갱신, 소리 감지 시작
4. 데스크톱이 뜨면 `kiosk_app.py`(모니터 UI)가 자동 실행됨
   - `system_status/recorder`를 실시간 구독해 로딩 중이면 상단에 안내 배너 표시
   - 와이파이 미연결 시에도 별도 배너로 안내
5. 소리가 감지되면 녹음 → STT 변환 → 카테고리 자동 분류(점검/화재/긴급/안내) → 제목 생성 → Firebase 업로드
6. 업로드 성공 시 카테고리에 맞는 LED 알림 시작. 모니터 UI에서 해당 방송을 터치해 펼치면 자동으로 읽음 처리(`isRead: true`)되어 LED가 즉시 꺼짐
7. 모니터 UI에서 방송 항목마다 삭제 버튼으로 Firestore 문서를 바로 삭제할 수 있음

---

## 최초 설치

### 1. 패키지 설치
```bash
sudo apt update
sudo apt install -y bluetooth bluez libbluetooth-dev python3-dbus python3-gi portaudio19-dev python3-tk

pip install sounddevice soundfile numpy --break-system-packages
pip install pybluez2 --break-system-packages
pip install faster-whisper firebase-admin --break-system-packages
```

### 2. 파일 배치
- `.py` 파일들을 모두 `/home/ask/catch_soriping/`에 배치
- Firebase 서비스 계정 키(JSON)도 같은 폴더에 넣고, `config.py`의 `FIREBASE_KEY_PATH`가 그 파일명과 일치하는지 확인

### 3. 블루투스/LED 초기 설정 (최초 1회, 터미널에서 직접 실행)
```bash
echo none | sudo tee /sys/class/leds/ACT/trigger
echo none | sudo tee /sys/class/leds/PWR/trigger
```

### 4. 시스템 스크립트/서비스 등록
```bash
# 스크립트 배치
sudo cp bt-discoverable.sh led-setup.sh start_main.sh start_kiosk.sh /usr/local/bin/
sudo chmod +x /usr/local/bin/bt-discoverable.sh /usr/local/bin/led-setup.sh /usr/local/bin/start_main.sh /usr/local/bin/start_kiosk.sh

# 서비스 배치
sudo cp bt-wifi-setup.service bt-agent.service ble-wifi-setup.service led-setup.service soriping-main.service /etc/systemd/system/

# 모니터 UI 자동 실행 등록 (데스크톱 세션용)
mkdir -p ~/.config/autostart
cp kiosk-ui.desktop ~/.config/autostart/kiosk-ui.desktop

# 서비스 등록 및 실행
sudo systemctl daemon-reload
sudo systemctl enable --now bt-agent.service
sudo systemctl enable --now bt-wifi-setup.service
sudo systemctl enable --now ble-wifi-setup.service
sudo systemctl enable --now led-setup.service
sudo systemctl enable --now soriping-main.service
```

### 5. 데스크톱 자동 로그인 활성화 (모니터 UI 자동 실행에 필요)
```bash
sudo raspi-config
```
`System Options` → `Boot / Auto Login` → `Desktop Autologin` 선택. 데스크톱에 자동 로그인되어야 `kiosk_app.py`가 부팅 후 자동으로 뜹니다.

### 6. 일반 사용자 권한으로 LED 쓰기 (udev, 안 되면 systemd 서비스로 대체됨)
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
cat /home/ask/catch_soriping/logs/kiosk_app.log
cat /home/ask/catch_soriping/logs/bt_wifi_setup.log
cat /home/ask/catch_soriping/logs/bt_agent.log
cat /home/ask/catch_soriping/logs/ble_wifi_gatt_server.log
```
파일 하나당 최대 2MB까지 쌓이고, 넘으면 자동으로 이전 로그(최대 3개)를 남기고 정리됩니다.

`kiosk_app.py`를 데스크톱 자동 실행으로 띄운 경우, 콘솔 출력은 별도로 아래에도 쌓입니다:
```bash
cat /home/ask/catch_soriping/logs/kiosk_app_stdout.log
```

---

## Firestore 데이터 구조

### `announcements` 컬렉션 (안내방송 각 건)
| 필드 | 타입 | 설명 |
|---|---|---|
| `title` | string | 카테고리 태그 (`[점검]`, `[화재]`, `[긴급]`, `[안내]`) |
| `text` | string | STT로 변환된 방송 전체 내용 |
| `category` | string | `general` / `maintenance` / `emergency` / `fire` |
| `timestamp` | timestamp | 업로드 시각 |
| `isRead` | boolean | 읽음 여부. 모니터 UI에서 항목을 펼치면 `true`로 갱신됨 |

### `system_status` 컬렉션 (시스템 상태)
| 문서 | 필드 | 설명 |
|---|---|---|
| `recorder` | `state` (`loading`/`ready`), `message`, `updatedAt` | `main.py`의 STT 엔진 로딩 상태. 모니터 UI가 이걸 보고 준비 중 배너를 띄움 |

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

Firestore에서 해당 공지의 `isRead`가 `true`로 바뀌는 순간(모니터 UI에서 펼치거나, 폰 앱에서 읽음 처리) 실시간으로 감지되어 LED가 즉시 꺼집니다.

---

## 모니터 UI (kiosk_app.py) 사용법

- **아파트 실시간 방송 페이지**: 방송 목록을 최신순으로 표시. 항목을 터치하면 펼쳐지며 자동 읽음 처리(LED 소등), 하단 🗑 삭제 버튼으로 삭제 가능. 우측 상단 "기기 연결 설정" 버튼으로 이동.
- **기기 연결 설정 페이지**: 현재 연결된 와이파이 표시, 주변 와이파이 스캔·새로고침, 네트워크 터치 시 비밀번호 입력(화면 키보드 포함) 후 연결. 좌측 상단 "← 방송 목록" 버튼으로 복귀.
- 개발 중 전체화면을 빠져나오려면 `Esc` 키.

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
| VS Code에서 시스템 폴더(`/usr/local/bin`, `/etc/systemd/system`) 저장 시 `EACCES` | 홈 폴더에 저장 후 터미널에서 `sudo cp`로 이동 |
| `no display name and no $DISPLAY environment variable` (kiosk_app.py 실행 시) | GUI는 데스크톱 세션이 있어야 실행 가능. SSH에서는 `DISPLAY=:0 python3 kiosk_app.py`로 실행하거나 파이 모니터에서 직접 실행 |
| 와이파이 연결 시 `key-mgmt: property is missing` | 이전에 저장된 연결 프로필이 꼬인 것. `sudo nmcli connection delete <SSID>` 후 재시도 |
| kiosk_app.py에서 목록이 안 뜨는데 로그엔 정상 갱신됨 | Tkinter 렌더링 코드 자체의 예외일 가능성. 로그 확인 후 안 되면 `doc.to_dict()` 등 Firestore 문서 접근 메서드명 확인 |
| 팝업창이 비어있게 뜸 | `grab_set()`을 위젯 생성 **이전에** 호출하면 창이 아직 안 그려져 조용히 실패함. 위젯을 다 만든 뒤 `update_idletasks()` → `grab_set()` 순서로 호출해야 함 |

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
재부팅 후 위 상태 확인 명령, `sudo journalctl -u soriping-main.service -f`로 `main.py` 자동 실행을, 데스크톱 화면에서 `kiosk_app.py`가 자동으로 뜨는지 확인하세요.
