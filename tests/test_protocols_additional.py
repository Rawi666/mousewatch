from mousewatch.protocols import (
    ATK_CMD_GET_BATTERY,
    ATK_CMD_LEN,
    ATK_REPORT_ID,
    ATK_WIRED_PID,
    ATK_WIRELESS_PID,
    AtkProtocolAdapter,
    MchoseProtocolAdapter,
    _safe_int,
    autodetect_any,
    get_protocol_by_key,
    get_protocol_order,
)
import mousewatch.protocols as protocols_mod


class DummyCommon:
    @staticmethod
    def query_after_throwaway(_protocol, _path, settle_delay=0.05):
        _ = settle_delay
        return {"battery_level": 55, "charge_status": 1, "connect_mode": 1}


class FakeHidDevice:
    def __init__(self, raw=None, fail_open=False, fail_read=False):
        self.raw = raw if raw is not None else []
        self.fail_open = fail_open
        self.fail_read = fail_read
        self.opened_path = None
        self.closed = False
        self.written = None

    def open_path(self, path):
        if self.fail_open:
            raise OSError("open failed")
        self.opened_path = path

    def set_nonblocking(self, _value):
        return None

    def write(self, payload):
        self.written = list(payload)
        return len(payload)

    def read(self, _size, timeout_ms=0):
        _ = timeout_ms
        if self.fail_read:
            raise ValueError("read failed")
        return self.raw

    def close(self):
        self.closed = True


class FakeHidModule:
    def __init__(self, devices=None, enumerated=None):
        self._device = devices
        self._enumerated = enumerated if enumerated is not None else []

    def device(self):
        return self._device

    def enumerate(self, _vid=None):
        return list(self._enumerated)



def _build_valid_raw_response(adapter, battery=73, charge=1, voltage_raw=39):
    frame = [0] * ATK_CMD_LEN
    frame[0] = ATK_CMD_GET_BATTERY
    frame[1] = 0x00
    frame[4] = 3
    frame[5] = battery
    frame[6] = charge
    frame[7] = voltage_raw
    frame[15] = adapter._frame_checksum(frame)
    return [ATK_REPORT_ID] + frame


def test_safe_int_and_protocol_lookup_helpers():
    assert _safe_int("10") == 10
    assert _safe_int("x", default=5) == 5

    assert get_protocol_by_key(" MCHOSE ").key == "mchose"
    assert get_protocol_by_key("atk").key == "atk"
    assert get_protocol_by_key("missing") is None

    ordered = get_protocol_order("atk")
    assert ordered[0].key == "atk"


def test_autodetect_any_returns_first_success():
    class P1:
        def autodetect(self, _common):
            return None

    class P2:
        def autodetect(self, _common):
            return "Model", b"path", {"battery_level": 12}

    result = autodetect_any(object(), [P1(), P2()])
    assert result[0].__class__.__name__ == "P2"
    assert result[1] == "Model"


def test_mchose_decode_input_report_and_debug_lines():
    adapter = MchoseProtocolAdapter()
    # Build an encoded raw packet where decoded bytes contain an E2 report.
    decoded = bytes([0x11, 0xE2, 0x00, 0x01, 0x02, 85, 0, 0, 65, 66])
    raw = [b ^ 0xFF for b in decoded]

    decoded_out, parsed = adapter.decode_input_report(raw)

    assert decoded_out[1] == 0xE2
    assert parsed is not None
    assert parsed["battery_level"] == 85
    assert parsed["charging"] is True

    lines = []
    adapter.append_debug_input_details(lines, decoded_out)
    assert any("batteryLevel" in line for line in lines)


def test_mchose_autodetect_falls_back_to_product_string(monkeypatch):
    adapter = MchoseProtocolAdapter()

    monkeypatch.setattr(
        protocols_mod,
        "find_mchose_devices",
        lambda: [{"path": b"p", "product_string": "MCHOSE L7"}],
    )
    monkeypatch.setattr(protocols_mod, "resolve_model_from_response", lambda _resp: None)

    result = adapter.autodetect(DummyCommon)

    assert result[0] == "L7"
    assert result[1] == b"p"


def test_atk_command_build_extract_and_parse_helpers():
    adapter = AtkProtocolAdapter()
    command = adapter._build_get_battery_command()

    assert len(command) == ATK_CMD_LEN
    assert command[0] == ATK_CMD_GET_BATTERY
    assert command[15] == adapter._frame_checksum(command)

    full = [ATK_REPORT_ID] + command
    assert adapter._extract_frame(full) == command
    assert adapter._extract_frame(command) == command
    assert adapter._extract_frame([1, 2, 3]) is None


def test_atk_discover_devices_sorted_and_deduped(monkeypatch):
    adapter = AtkProtocolAdapter()
    enumerated = [
        {
            "path": b"z",
            "product_id": ATK_WIRED_PID,
            "usage_page": 0x0000,
            "usage": 0x02,
            "interface_number": 2,
        },
        {
            "path": b"a",
            "product_id": ATK_WIRELESS_PID,
            "usage_page": 0xFF00,
            "usage": 0x01,
            "interface_number": 1,
        },
        {
            "path": b"a",
            "product_id": ATK_WIRELESS_PID,
            "usage_page": 0xFF00,
            "usage": 0x01,
            "interface_number": 1,
        },
        {"path": b"x", "product_id": 0x9999, "usage_page": 0xFF00, "usage": 0x01, "interface_number": 1},
    ]
    monkeypatch.setattr(protocols_mod, "hid", FakeHidModule(enumerated=enumerated))

    devices = adapter.discover_devices()

    assert [d["path"] for d in devices] == [b"a", b"z"]


def test_atk_find_wired_device(monkeypatch):
    adapter = AtkProtocolAdapter()
    monkeypatch.setattr(
        adapter,
        "discover_devices",
        lambda: [
            {"path": b"w", "product_id": ATK_WIRED_PID, "product_string": "ATK A9 Plus"},
            {"path": b"d", "product_id": ATK_WIRELESS_PID, "product_string": "NANO Dongle"},
        ],
    )

    wired = adapter.find_wired_device()

    assert wired == {"name": "ATK A9 Plus", "path": b"w"}


def test_atk_query_battery_success_and_closes_device(monkeypatch):
    adapter = AtkProtocolAdapter()
    raw = _build_valid_raw_response(adapter, battery=66, charge=0)
    fake_device = FakeHidDevice(raw=raw)
    monkeypatch.setattr(protocols_mod, "hid", FakeHidModule(devices=fake_device))

    resp = adapter.query_battery(b"/dev/hidraw1")

    assert resp is not None
    assert resp["battery_level"] == 66
    assert resp["charge_status"] == 0
    assert fake_device.opened_path == b"/dev/hidraw1"
    assert fake_device.written[0] == ATK_REPORT_ID
    assert fake_device.closed is True


def test_atk_query_battery_handles_open_error(monkeypatch):
    adapter = AtkProtocolAdapter()
    fake_device = FakeHidDevice(raw=[], fail_open=True)
    monkeypatch.setattr(protocols_mod, "hid", FakeHidModule(devices=fake_device))

    resp = adapter.query_battery(b"path")

    assert resp is None


def test_atk_format_and_model_helpers():
    adapter = AtkProtocolAdapter()

    assert adapter.format_model_name("ATK A9 Plus") == "ATK A9 Plus"
    assert adapter.format_model_name("A9 Plus") == "ATK A9 Plus"
    assert "Wireless" in adapter.format_status_text("A9 Plus", 50, False)
    assert "Charging" in adapter.format_status_text("A9 Plus", 0, True)
    assert adapter.is_known_model("a9 plus") is True
    assert adapter.is_known_model("unknown") is False


def test_atk_decode_input_report_and_debug_lines():
    adapter = AtkProtocolAdapter()
    raw = _build_valid_raw_response(adapter, battery=44, charge=1, voltage_raw=40)

    decoded, parsed = adapter.decode_input_report(raw)

    assert len(decoded) == ATK_CMD_LEN
    assert parsed is not None
    assert parsed["battery_level"] == 44
    assert parsed["charging"] is True

    lines = []
    adapter.append_debug_input_details(lines, decoded)
    assert any("batteryLevel" in line for line in lines)
