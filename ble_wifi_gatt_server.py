#!/usr/bin/env python3
"""
Raspberry Pi BLE(GATT) Wi-Fi 프로비저닝 서버 - iOS/Android 공용
사용법/설정/UUID 스펙은 README.md 참고.
"""

import json
import subprocess
import dbus
import dbus.exceptions
import dbus.mainloop.glib
import dbus.service
from gi.repository import GLib

from logger_setup import get_logger

logger = get_logger("ble_wifi_gatt_server")

BLUEZ_SERVICE_NAME = "org.bluez"
GATT_MANAGER_IFACE = "org.bluez.GattManager1"
LE_ADVERTISING_MANAGER_IFACE = "org.bluez.LEAdvertisingManager1"
DBUS_OM_IFACE = "org.freedesktop.DBus.ObjectManager"
DBUS_PROP_IFACE = "org.freedesktop.DBus.Properties"

GATT_SERVICE_IFACE = "org.bluez.GattService1"
GATT_CHRC_IFACE = "org.bluez.GattCharacteristic1"

SERVICE_UUID = "12345678-1234-5678-1234-56789abcdef0"
CONFIG_CHAR_UUID = "12345678-1234-5678-1234-56789abcdef1"  # Write (폰->파이)
RESULT_CHAR_UUID = "12345678-1234-5678-1234-56789abcdef2"  # Notify (파이->폰)

LOCAL_NAME = "RaspberryPi-WiFiSetup"

mainloop = None


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


class InvalidArgsException(dbus.exceptions.DBusException):
    _dbus_error_name = "org.freedesktop.DBus.Error.InvalidArgs"


class Application(dbus.service.Object):
    def __init__(self, bus):
        self.path = "/"
        self.services = []
        dbus.service.Object.__init__(self, bus, self.path)
        self.add_service(WifiService(bus, 0))

    def get_path(self):
        return dbus.ObjectPath(self.path)

    def add_service(self, service):
        self.services.append(service)

    @dbus.service.method(DBUS_OM_IFACE, out_signature="a{oa{sa{sv}}}")
    def GetManagedObjects(self):
        response = {}
        for service in self.services:
            response[service.get_path()] = service.get_properties()
            for chrc in service.get_characteristics():
                response[chrc.get_path()] = chrc.get_properties()
        return response


class Service(dbus.service.Object):
    PATH_BASE = "/org/bluez/soriping/service"

    def __init__(self, bus, index, uuid, primary):
        self.path = self.PATH_BASE + str(index)
        self.bus = bus
        self.uuid = uuid
        self.primary = primary
        self.characteristics = []
        dbus.service.Object.__init__(self, bus, self.path)

    def get_properties(self):
        return {
            GATT_SERVICE_IFACE: {
                "UUID": self.uuid,
                "Primary": self.primary,
                "Characteristics": dbus.Array(
                    [c.get_path() for c in self.characteristics], signature="o"
                ),
            }
        }

    def get_path(self):
        return dbus.ObjectPath(self.path)

    def add_characteristic(self, characteristic):
        self.characteristics.append(characteristic)

    def get_characteristics(self):
        return self.characteristics

    @dbus.service.method(DBUS_PROP_IFACE, in_signature="s", out_signature="a{sv}")
    def GetAll(self, interface):
        if interface != GATT_SERVICE_IFACE:
            raise InvalidArgsException()
        return self.get_properties()[GATT_SERVICE_IFACE]


class Characteristic(dbus.service.Object):
    def __init__(self, bus, index, uuid, flags, service):
        self.path = service.path + "/char" + str(index)
        self.bus = bus
        self.uuid = uuid
        self.service = service
        self.flags = flags
        self.notifying = False
        dbus.service.Object.__init__(self, bus, self.path)

    def get_properties(self):
        return {
            GATT_CHRC_IFACE: {
                "Service": self.service.get_path(),
                "UUID": self.uuid,
                "Flags": self.flags,
            }
        }

    def get_path(self):
        return dbus.ObjectPath(self.path)

    @dbus.service.method(DBUS_PROP_IFACE, in_signature="s", out_signature="a{sv}")
    def GetAll(self, interface):
        if interface != GATT_CHRC_IFACE:
            raise InvalidArgsException()
        return self.get_properties()[GATT_CHRC_IFACE]

    @dbus.service.method(GATT_CHRC_IFACE, in_signature="a{sv}", out_signature="ay")
    def ReadValue(self, options):
        return dbus.Array([], signature="y")

    @dbus.service.method(GATT_CHRC_IFACE, in_signature="aya{sv}")
    def WriteValue(self, value, options):
        pass

    @dbus.service.method(GATT_CHRC_IFACE)
    def StartNotify(self):
        self.notifying = True

    @dbus.service.method(GATT_CHRC_IFACE)
    def StopNotify(self):
        self.notifying = False


class WifiConfigCharacteristic(Characteristic):
    """폰 -> 파이: 와이파이 정보(JSON)를 받는 특성 (Write)"""

    def __init__(self, bus, index, service, result_char):
        Characteristic.__init__(self, bus, index, CONFIG_CHAR_UUID, ["write"], service)
        self.result_char = result_char

    @dbus.service.method(GATT_CHRC_IFACE, in_signature="aya{sv}")
    def WriteValue(self, value, options):
        raw = bytes(value).decode("utf-8", errors="ignore").strip()
        logger.info(f"수신: {raw}")

        try:
            info = json.loads(raw)
        except json.JSONDecodeError:
            self.result_char.send_result("error", "JSON 형식이 올바르지 않습니다.")
            return

        ssid = info.get("ssid")
        password = info.get("password", "")

        if not ssid:
            self.result_char.send_result("error", "ssid 값이 없습니다.")
            return

        ok, msg = connect_wifi(ssid, password)
        self.result_char.send_result("ok" if ok else "error", msg)


class WifiResultCharacteristic(Characteristic):
    """파이 -> 폰: 처리 결과(JSON)를 알려주는 특성 (Notify/Read)"""

    def __init__(self, bus, index, service):
        Characteristic.__init__(
            self, bus, index, RESULT_CHAR_UUID, ["read", "notify"], service
        )
        self.last_value = []

    def send_result(self, status: str, message: str):
        payload = json.dumps({"status": status, "message": message}, ensure_ascii=False)
        logger.info(f"응답: {payload}")
        value = [dbus.Byte(b) for b in payload.encode("utf-8")]
        self.last_value = value
        if self.notifying:
            self.PropertiesChanged(
                GATT_CHRC_IFACE, {"Value": dbus.Array(value, signature="y")}, []
            )

    @dbus.service.method(GATT_CHRC_IFACE, in_signature="a{sv}", out_signature="ay")
    def ReadValue(self, options):
        return dbus.Array(self.last_value, signature="y")

    @dbus.service.signal(DBUS_PROP_IFACE, signature="sa{sv}as")
    def PropertiesChanged(self, interface, changed, invalidated):
        pass


class WifiService(Service):
    def __init__(self, bus, index):
        Service.__init__(self, bus, index, SERVICE_UUID, True)
        result_char = WifiResultCharacteristic(bus, 1, self)
        config_char = WifiConfigCharacteristic(bus, 0, self, result_char)
        self.add_characteristic(config_char)
        self.add_characteristic(result_char)


class Advertisement(dbus.service.Object):
    PATH = "/org/bluez/soriping/advertisement0"

    def __init__(self, bus):
        dbus.service.Object.__init__(self, bus, self.PATH)
        self.ad_type = "peripheral"
        self.service_uuids = [SERVICE_UUID]
        self.local_name = LOCAL_NAME
        self.include_tx_power = True

    def get_properties(self):
        return {
            "org.bluez.LEAdvertisement1": {
                "Type": self.ad_type,
                "ServiceUUIDs": dbus.Array(self.service_uuids, signature="s"),
                "LocalName": dbus.String(self.local_name),
                "IncludeTxPower": dbus.Boolean(self.include_tx_power),
            }
        }

    def get_path(self):
        return dbus.ObjectPath(self.PATH)

    @dbus.service.method(DBUS_PROP_IFACE, in_signature="s", out_signature="a{sv}")
    def GetAll(self, interface):
        return self.get_properties()["org.bluez.LEAdvertisement1"]

    @dbus.service.method("org.bluez.LEAdvertisement1")
    def Release(self):
        logger.info("광고 해제됨")


def find_adapter(bus):
    remote_om = dbus.Interface(bus.get_object(BLUEZ_SERVICE_NAME, "/"), DBUS_OM_IFACE)
    objects = remote_om.GetManagedObjects()
    for o, props in objects.items():
        if GATT_MANAGER_IFACE in props and LE_ADVERTISING_MANAGER_IFACE in props:
            return o
    return None


def register_app_cb():
    logger.info("GATT 애플리케이션 등록 완료")


def register_app_error_cb(error):
    logger.error(f"GATT 애플리케이션 등록 실패: {error}")
    mainloop.quit()


def register_ad_cb():
    logger.info(f"광고 시작됨 (이름: {LOCAL_NAME})")


def register_ad_error_cb(error):
    logger.error(f"광고 등록 실패: {error}")
    mainloop.quit()


def main():
    global mainloop

    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    bus = dbus.SystemBus()

    adapter_path = find_adapter(bus)
    if not adapter_path:
        logger.error("GATT/Advertising을 지원하는 블루투스 어댑터를 찾을 수 없습니다.")
        return

    service_manager = dbus.Interface(
        bus.get_object(BLUEZ_SERVICE_NAME, adapter_path), GATT_MANAGER_IFACE
    )
    ad_manager = dbus.Interface(
        bus.get_object(BLUEZ_SERVICE_NAME, adapter_path), LE_ADVERTISING_MANAGER_IFACE
    )

    app = Application(bus)
    adv = Advertisement(bus)

    mainloop = GLib.MainLoop()

    service_manager.RegisterApplication(
        app.get_path(), {}, reply_handler=register_app_cb, error_handler=register_app_error_cb
    )
    ad_manager.RegisterAdvertisement(
        adv.get_path(), {}, reply_handler=register_ad_cb, error_handler=register_ad_error_cb
    )

    logger.info("Wi-Fi 프로비저닝 GATT 서버 대기 중...")
    try:
        mainloop.run()
    except KeyboardInterrupt:
        logger.info("종료합니다.")
        ad_manager.UnregisterAdvertisement(adv.get_path())
        service_manager.UnregisterApplication(app.get_path())


if __name__ == "__main__":
    main()
