from __future__ import annotations

import time
from typing import Iterable, Protocol

from device_ids import (
    ATK_PRODUCT_ID_WIRED_MOUSE,
    ATK_PRODUCT_ID_WIRELESS_DONGLE,
    ATK_PRODUCT_IDS,
    ATK_VENDOR_ID,
)
from mchose_protocol import (
    MOUSE_DB,
    find_mchose_devices,
    find_wired_mchose,
    pick_model,
    query_battery,
    resolve_model_from_response,
    xor_decode,
)
from mw_platform import hid


class MouseProtocolAdapter(Protocol):
    key: str
    display_name: str
    input_section_title: str
    supports_input_listener: bool

    def autodetect(self, common_cls) -> tuple[str, bytes, dict] | None:
        ...

    def discover_devices(self) -> list[dict]:
        ...

    def find_wired_device(self) -> dict | None:
        ...

    def query_battery(self, path: bytes) -> dict | None:
        ...

    def status_from_response(self, resp: dict) -> tuple[int, bool]:
        ...

    def format_status_text(self, model: str, level: int, charging: bool) -> str:
        ...

    def format_model_name(self, model: str) -> str:
        ...

    def is_known_model(self, model: str) -> bool:
        ...

    def list_models(self) -> list[str]:
        ...

    def pick_model(self) -> str:
        ...

    def decode_input_report(self, raw: list[int]) -> tuple[list[int], dict | None]:
        ...

    def append_debug_input_details(self, lines: list[str], decoded: list[int]):
        ...


class MchoseProtocolAdapter:
    key = "mchose"
    display_name = "MCHOSE"
    input_section_title = "Last E2 Input Report"
    supports_input_listener = True

    def autodetect(self, common_cls) -> tuple[str, bytes, dict] | None:
        devices = self.discover_devices()
        if not devices:
            return None

        for dev in devices:
            resp = common_cls.query_after_throwaway(self, dev["path"])
            if resp is None:
                continue

            model = resolve_model_from_response(resp)
            if model is None:
                name = (dev.get("product_string") or "").replace("MCHOSE ", "")
                if name:
                    model = name

            if model is None:
                continue

            return model, dev["path"], resp

        return None

    def discover_devices(self) -> list[dict]:
        return find_mchose_devices()

    def find_wired_device(self) -> dict | None:
        return find_wired_mchose()

    def query_battery(self, path: bytes) -> dict | None:
        return query_battery(path)

    def status_from_response(self, resp: dict) -> tuple[int, bool]:
        level = resp["battery_level"]
        charging = (resp["charge_status"] != 0 or resp["connect_mode"] == 0)
        return level, charging

    def format_model_name(self, model: str) -> str:
        return f"{self.display_name} {model}"

    def format_status_text(self, model: str, level: int, charging: bool) -> str:
        if level == 0 and charging:
            return f"{self.format_model_name(model)} - Charging"
        status = "Charging" if charging else "Wireless"
        return f"{self.format_model_name(model)} - {level}% ({status})"

    def is_known_model(self, model: str) -> bool:
        return model in MOUSE_DB

    def list_models(self) -> list[str]:
        return sorted(MOUSE_DB.keys())

    def pick_model(self) -> str:
        return pick_model()

    def decode_input_report(self, raw: list[int]) -> tuple[list[int], dict | None]:
        decoded = list(xor_decode(bytes(raw)))
        if len(decoded) < 6 or decoded[1] != 0xE2:
            return decoded, None

        charge_status = decoded[4]
        battery_level = decoded[5]
        if battery_level == 0 or battery_level > 100:
            return decoded, None

        return decoded, {
            "charge_status": charge_status,
            "battery_level": battery_level,
            "charging": charge_status != 0,
        }

    def append_debug_input_details(self, lines: list[str], decoded: list[int]):
        if len(decoded) < 6:
            return

        lines.append(f"  [0] Report ID:    0x{decoded[0]:02X}")
        lines.append(f"  [1] Notification: 0x{decoded[1]:02X}")
        lines.append(f"  [2] Sub-type hi:  0x{decoded[2]:02X}")
        lines.append(f"  [3] Sub-type lo:  0x{decoded[3]:02X}")
        lines.append(f"  [4] chargeStatus: {decoded[4]}")
        lines.append(f"  [5] batteryLevel: {decoded[5]}%")
        name_bytes = bytes(b for b in decoded[8:] if 0x20 <= b < 0x7F)
        if name_bytes:
            lines.append(
                f"  [8+] Model name:  {name_bytes.decode('ascii', errors='replace')}"
            )


ATK_WIRELESS_PID = ATK_PRODUCT_ID_WIRELESS_DONGLE
ATK_WIRED_PID = ATK_PRODUCT_ID_WIRED_MOUSE
ATK_PIDS = set(ATK_PRODUCT_IDS)
ATK_MODEL_A9_PLUS = "A9 Plus"

ATK_REPORT_ID = 0x08
ATK_CMD_LEN = 0x10
ATK_CMD_GET_BATTERY = 0x04
ATK_USAGE_PAGE_PREFERRED = 0xFF00
ATK_USAGE_PAGES_ALLOWED = {0xFF00, 0x0000}


def _pick_from_list(label: str, names: list[str]) -> str:
    print(f"\nAvailable {label} mouse models:\n")
    for i, name in enumerate(names, 1):
        print(f"  {i:2d}. {name}")
    print()

    while True:
        try:
            choice = input("Select model number: ").strip()
            idx = int(choice) - 1
            if 0 <= idx < len(names):
                return names[idx]
        except (ValueError, EOFError):
            pass
        print("Invalid selection, try again.")


def _safe_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


class AtkProtocolAdapter:
    key = "atk"
    display_name = "ATK"
    input_section_title = "Last ATK Input Frame"
    supports_input_listener = False
    _known_models = [
        ATK_MODEL_A9_PLUS,
    ]

    def _device_score(self, dev: dict) -> tuple:
        usage_page = _safe_int(dev.get("usage_page"))
        usage = _safe_int(dev.get("usage"))
        iface = _safe_int(dev.get("interface_number"), 999)
        pid = _safe_int(dev.get("product_id"))
        is_wireless = pid == ATK_WIRELESS_PID
        return (
            usage_page != ATK_USAGE_PAGE_PREFERRED,
            usage_page not in ATK_USAGE_PAGES_ALLOWED,
            usage != 0x01,
            not is_wireless,
            iface,
        )

    def _normalized_model_name(self, product_string: str | None) -> str:
        if not product_string:
            return "Unknown"
        name = product_string.strip()
        lower_name = name.lower()
        if "nano dongle" in lower_name:
            return ATK_MODEL_A9_PLUS
        if "a9 plus" in lower_name:
            return ATK_MODEL_A9_PLUS
        for prefix in ("Compx ", "ATK ", "NK "):
            if name.startswith(prefix):
                name = name[len(prefix):]
        return name or "Unknown"

    def autodetect(self, common_cls) -> tuple[str, bytes, dict] | None:
        devices = self.discover_devices()
        if not devices:
            return None

        for dev in devices:
            resp = common_cls.query_after_throwaway(self, dev["path"], settle_delay=0.05)
            if resp is None:
                continue
            model = self._normalized_model_name(dev.get("product_string"))
            return model, dev["path"], resp
        return None

    def discover_devices(self) -> list[dict]:
        results = []
        seen_paths = set()
        for dev in hid.enumerate(ATK_VENDOR_ID):
            pid = _safe_int(dev.get("product_id"))
            if pid not in ATK_PIDS:
                continue
            path = dev.get("path")
            if not path or path in seen_paths:
                continue
            seen_paths.add(path)
            results.append(dev)
        results.sort(key=self._device_score)
        return results

    def find_wired_device(self) -> dict | None:
        wired = [d for d in self.discover_devices() if _safe_int(d.get("product_id")) == ATK_WIRED_PID]
        if not wired:
            return None
        dev = wired[0]
        return {
            "name": dev.get("product_string") or "ATK",
            "path": dev["path"],
        }

    def _build_get_battery_command(self) -> list[int]:
        frame = [0] * ATK_CMD_LEN
        frame[0] = ATK_CMD_GET_BATTERY
        frame[1] = 0x00  # status
        frame[2] = 0x00  # eeprom address (hi)
        frame[3] = 0x00  # eeprom address (lo)
        frame[4] = 0x00  # data valid length
        # frame[5:15] left as zeros

        checksum_base = (
            ATK_REPORT_ID
            + frame[0]
            + frame[1]
            + ((frame[2] << 8) | frame[3])
            + frame[4]
            + sum(frame[5:15])
        ) & 0xFF
        frame[15] = (0x55 - checksum_base) & 0xFF
        return frame

    def _extract_frame(self, raw: list[int]) -> list[int] | None:
        if len(raw) >= ATK_CMD_LEN + 1 and raw[0] == ATK_REPORT_ID:
            return raw[1:1 + ATK_CMD_LEN]
        if len(raw) >= ATK_CMD_LEN:
            return raw[:ATK_CMD_LEN]
        return None

    def _parse_battery_frame(self, frame: list[int]) -> dict | None:
        if len(frame) != ATK_CMD_LEN:
            return None

        command_id = frame[0]
        status = frame[1]
        data_len = frame[4]
        data = frame[5:15]

        if command_id != ATK_CMD_GET_BATTERY:
            return None
        if status != 0x00:
            return None
        if data_len > len(data):
            return None

        battery_level = data[0]
        charge_status = data[1]
        voltage_raw = data[2]

        if battery_level > 100:
            return None

        return {
            "battery_level": battery_level,
            "charge_status": charge_status,
            "charging": charge_status != 0,
            "voltage": voltage_raw / 10.0,
            "raw_frame": frame,
        }

    def query_battery(self, path: bytes) -> dict | None:
        dev = None
        try:
            dev = hid.device()
            dev.open_path(path)
            dev.set_nonblocking(False)

            command = self._build_get_battery_command()
            dev.write([ATK_REPORT_ID] + command)

            raw = dev.read(64, timeout_ms=800)
            if not raw:
                return None

            frame = self._extract_frame(list(raw))
            if frame is None:
                return None

            return self._parse_battery_frame(frame)
        except Exception:
            return None
        finally:
            if dev is not None:
                try:
                    dev.close()
                except Exception:
                    pass

    def status_from_response(self, resp: dict) -> tuple[int, bool]:
        level = _safe_int(resp.get("battery_level"))
        charging = _safe_int(resp.get("charge_status")) != 0
        return level, charging

    def format_model_name(self, model: str) -> str:
        if model.upper().startswith("ATK "):
            return model
        return f"{self.display_name} {model}"

    def format_status_text(self, model: str, level: int, charging: bool) -> str:
        if level == 0 and charging:
            return f"{self.format_model_name(model)} - Charging"
        status = "Charging" if charging else "Wireless"
        return f"{self.format_model_name(model)} - {level}% ({status})"

    def is_known_model(self, model: str) -> bool:
        wanted = model.strip().lower()
        return any(m.lower() == wanted for m in self._known_models)

    def list_models(self) -> list[str]:
        return sorted(self._known_models)

    def pick_model(self) -> str:
        return _pick_from_list(self.display_name, self.list_models())

    def decode_input_report(self, raw: list[int]) -> tuple[list[int], dict | None]:
        frame = self._extract_frame(raw)
        if frame is None:
            return raw, None

        parsed = self._parse_battery_frame(frame)
        if parsed is None:
            return frame, None

        return frame, {
            "charge_status": parsed["charge_status"],
            "battery_level": parsed["battery_level"],
            "charging": parsed["charging"],
        }

    def append_debug_input_details(self, lines: list[str], decoded: list[int]):
        if len(decoded) < ATK_CMD_LEN:
            lines.append("  Frame too short to decode")
            return

        command_id = decoded[0]
        status = decoded[1]
        data_len = decoded[4]
        data = decoded[5:15]
        lines.append(f"  [0] cmd_id:       0x{command_id:02X}")
        lines.append(f"  [1] status:       0x{status:02X}")
        lines.append(f"  [4] data_len:     {data_len}")

        if data_len >= 1:
            lines.append(f"  [5] batteryLevel: {data[0]}%")
        if data_len >= 2:
            lines.append(f"  [6] chargeStatus: {data[1]}")
        if data_len >= 3:
            lines.append(f"  [7] voltage:      {data[2] / 10.0:.1f}V")


_PROTOCOLS: list[MouseProtocolAdapter] = [
    MchoseProtocolAdapter(),
    AtkProtocolAdapter(),
]


def get_protocols() -> list[MouseProtocolAdapter]:
    return list(_PROTOCOLS)


def get_protocol_keys() -> list[str]:
    return [p.key for p in _PROTOCOLS]


def get_protocol_by_key(key: str) -> MouseProtocolAdapter | None:
    wanted = key.strip().lower()
    for protocol in _PROTOCOLS:
        if protocol.key == wanted:
            return protocol
    return None


def get_protocol_order(preferred_key: str | None) -> list[MouseProtocolAdapter]:
    if not preferred_key:
        return get_protocols()

    preferred = get_protocol_by_key(preferred_key)
    if preferred is None:
        return get_protocols()

    return [preferred] + [p for p in _PROTOCOLS if p.key != preferred.key]


def autodetect_any(common_cls, protocols: Iterable[MouseProtocolAdapter]) -> tuple[MouseProtocolAdapter, str, bytes, dict] | None:
    for protocol in protocols:
        result = protocol.autodetect(common_cls)
        if result is None:
            continue
        model, hid_path, resp = result
        return protocol, model, hid_path, resp
    return None