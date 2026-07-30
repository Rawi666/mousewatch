"""MCHOSE HID protocol implementation.

This module contains MCHOSE-specific discovery and battery query logic.
Other mouse protocols (for example ATK) are implemented in `protocols.py`.
"""

import struct
import time

try:
    from .device_ids import MCHOSE_VENDOR_IDS
    from .mw_platform import IS_LINUX, hid
except ImportError:
    from device_ids import MCHOSE_VENDOR_IDS
    from mw_platform import IS_LINUX, hid

ALL_VIDS = list(MCHOSE_VENDOR_IDS)

MOUSE_DB = {
    "M7": {"inner_pid": 0x0020},
    "M7 Pro": {"inner_pid": 0x0030},
    "M7 Ultra": {"inner_pid": 0x0031},
    "L7": {"inner_pid": 0x00C0},
    "L7 Pro": {"inner_pid": 0x00B0},
    "L7 Pro+": {"inner_pid": 0x4015},
    "L7 Ultra": {"inner_pid": 0x00B1},
    "L7 Ultra+": {"inner_pid": 0x4016},
    "A7": {"inner_pid": 0x0070},
    "A7 Pro": {"inner_pid": 0x0010},
    "A7 Ultra": {"inner_pid": 0x0011},
    "A7 Ultra(RE)": {"inner_pid": 0x4110},
    "A7 V2 Pro": {"inner_pid": 0x4018},
    "A7 V2 Pro+": {"inner_pid": 0x4023},
    "A7 V2 Ultra": {"inner_pid": 0x4019},
    "A7 V2 Ultra+": {"inner_pid": 0x4021},
    "A7X Ultra": {"inner_pid": 0x4011},
    "K7 Ultra": {"inner_pid": 0x4150},
    "A5 V2 Ultra": {"inner_pid": 0x1101},
    "AX5 V2": {"inner_pid": 0x4010},
    "G3 Ultra 8K": {"inner_pid": 0x4762},
    "G3 Ultra 4K": {"inner_pid": 0x4762},
}

USAGE_PAGES = [0xFF01]
_LINUX_FALLBACK_USAGE_PAGES = [0x0000]

REPORT_ID = 0x11
CMD_GET_STATUS = 0x06


def xor_encode(data: list[int]) -> list[int]:
    return [b ^ 0xFF for b in data]


def xor_decode(data: bytes) -> bytes:
    return bytes(b ^ 0xFF for b in data)


def find_mchose_devices() -> list[dict]:
    """Enumerate HID devices and return likely MCHOSE battery-report interfaces."""
    results = []
    seen_paths = set()

    allowed_pages = set(USAGE_PAGES)
    if IS_LINUX:
        allowed_pages.update(_LINUX_FALLBACK_USAGE_PAGES)

    for vid in ALL_VIDS:
        for dev in hid.enumerate(vid):
            usage_page = dev.get("usage_page", 0)
            if usage_page in allowed_pages and dev["path"] not in seen_paths:
                seen_paths.add(dev["path"])
                results.append(dev)

    def _sort_key(d: dict) -> tuple:
        usage_page = d.get("usage_page", 0)
        iface = d.get("interface_number", 999)
        return (usage_page != 0xFF01, usage_page == 0x0000, iface)

    results.sort(key=_sort_key)
    return results


def find_wired_mchose() -> dict | None:
    """Check if a MCHOSE mouse is connected via USB cable (any usage page)."""
    best = None
    for vid in ALL_VIDS:
        for dev in hid.enumerate(vid):
            name = dev.get("product_string") or ""
            usage_page = dev.get("usage_page", 0)
            if best is None:
                best = {"name": name or "MCHOSE", "path": dev["path"]}
            if usage_page == 0xFF01:
                return {"name": name or "MCHOSE", "path": dev["path"]}
    return best


def query_battery(path: bytes) -> dict | None:
    """Send the status command and parse the response."""
    dev = None
    try:
        dev = hid.device()
        dev.open_path(path)
        dev.set_nonblocking(False)

        payload = [CMD_GET_STATUS] + [0x00] * 19
        encoded = xor_encode(payload)
        dev.send_feature_report([REPORT_ID] + encoded)

        time.sleep(0.05)

        raw = dev.get_feature_report(REPORT_ID, 21)

        if not raw or len(raw) < 12:
            return None

        decoded = xor_decode(bytes(raw[2:]))

        vid, pid = struct.unpack_from("<HH", decoded, 0)
        if vid == 0 and pid == 0:
            return None

        fw_version = struct.unpack_from("<I", decoded, 4)[0]
        status_byte = decoded[8]
        connect_mode = status_byte & 0x07
        connect_status = (status_byte >> 3) & 0x01
        battery_level = decoded[9]
        charge_status = decoded[10]

        # If this is not a valid MCHOSE status frame (for example, path switched
        # to another vendor), reject it so runtime failover can try other protocols.
        if battery_level > 100:
            return None

        return {
            "vid": vid,
            "pid": pid,
            "fw_version": fw_version,
            "connect_mode": connect_mode,
            "connect_status": connect_status,
            "battery_level": battery_level,
            "charge_status": charge_status,
        }
    except Exception as e:
        err = str(e)
        if "open failed" not in err.lower() and "read error" not in err.lower():
            print(f"  [!] HID error: {err}")
        return None
    finally:
        if dev is not None:
            try:
                dev.close()
            except OSError:
                print("  [!] Failed to close MCHOSE HID handle")


def resolve_model_from_response(resp: dict) -> str | None:
    """Match the inner PID from the status response to a model."""
    for name, info in MOUSE_DB.items():
        if resp["pid"] == info["inner_pid"]:
            return name
    return None


def pick_model() -> str:
    """Let the user pick a mouse model from the list."""
    names = sorted(MOUSE_DB.keys())
    print("\nAvailable MCHOSE mouse models:\n")
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