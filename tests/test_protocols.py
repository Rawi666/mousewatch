from mousewatch.mchose_protocol import query_battery
from mousewatch.protocols import ATK_CMD_GET_BATTERY, AtkProtocolAdapter


class _FakeMchoseDevice:
    def __init__(self):
        self.closed = False

    def open_path(self, _path):
        return None

    def set_nonblocking(self, _value):
        return None

    def send_feature_report(self, _payload):
        raise RuntimeError("boom")

    def close(self):
        self.closed = True


class _FakeHidModule:
    def __init__(self, device):
        self._device = device

    def device(self):
        return self._device


def _build_valid_atk_frame(adapter: AtkProtocolAdapter, battery: int = 54, charge: int = 1, voltage_raw: int = 39):
    frame = [0] * 16
    frame[0] = ATK_CMD_GET_BATTERY
    frame[1] = 0x00
    frame[4] = 3
    frame[5] = battery
    frame[6] = charge
    frame[7] = voltage_raw
    frame[15] = adapter._frame_checksum(frame)
    return frame


def test_atk_parse_accepts_valid_frame():
    adapter = AtkProtocolAdapter()
    frame = _build_valid_atk_frame(adapter, battery=80, charge=0, voltage_raw=37)

    parsed = adapter._parse_battery_frame(frame)

    assert parsed is not None
    assert parsed["battery_level"] == 80
    assert parsed["charge_status"] == 0
    assert parsed["charging"] is False
    assert parsed["voltage"] == 3.7


def test_atk_parse_rejects_bad_checksum():
    adapter = AtkProtocolAdapter()
    frame = _build_valid_atk_frame(adapter)
    frame[15] = (frame[15] + 1) & 0xFF

    assert adapter._parse_battery_frame(frame) is None


def test_atk_parse_accepts_non_binary_charge_state_as_charging():
    adapter = AtkProtocolAdapter()
    frame = _build_valid_atk_frame(adapter)
    frame[6] = 7
    frame[15] = adapter._frame_checksum(frame)

    parsed = adapter._parse_battery_frame(frame)
    assert parsed is not None
    assert parsed["charge_status"] == 7
    assert parsed["charging"] is True


def test_mchose_query_closes_device_on_exception(monkeypatch):
    import mousewatch.mchose_protocol as mchose_protocol

    fake_dev = _FakeMchoseDevice()
    monkeypatch.setattr(mchose_protocol, "hid", _FakeHidModule(fake_dev))

    result = query_battery(b"dummy")

    assert result is None
    assert fake_dev.closed is True
