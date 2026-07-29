from __future__ import annotations

from typing import Iterable, Protocol

from hid_protocol import (
    MOUSE_DB,
    find_mchose_devices,
    find_wired_mchose,
    pick_model,
    query_battery,
    resolve_model_from_response,
    xor_decode,
)


class MouseProtocolAdapter(Protocol):
    key: str
    display_name: str
    input_section_title: str

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


_PROTOCOLS: list[MouseProtocolAdapter] = [
    MchoseProtocolAdapter(),
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