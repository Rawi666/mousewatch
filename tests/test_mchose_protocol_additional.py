import struct

import mousewatch.mchose_protocol as mchose_protocol


class FakeMchoseDevice:
    def __init__(self, raw, raise_on_send=False):
        self.raw = raw
        self.raise_on_send = raise_on_send
        self.opened = None
        self.sent = None
        self.closed = False

    def open_path(self, path):
        self.opened = path

    def set_nonblocking(self, _value):
        return None

    def send_feature_report(self, payload):
        if self.raise_on_send:
            raise RuntimeError("send failed")
        self.sent = list(payload)

    def get_feature_report(self, _report_id, _length):
        return list(self.raw)

    def close(self):
        self.closed = True


class FakeHidModule:
    def __init__(self, device=None, enumerated=None):
        self._device = device
        self._enumerated = enumerated if enumerated is not None else {}

    def device(self):
        return self._device

    def enumerate(self, vid):
        return list(self._enumerated.get(vid, []))



def _build_status_frame(vid=0x3837, pid=0x4019, battery=75, charge=1, connect_mode=1):
    payload = bytearray(11)
    struct.pack_into("<HH", payload, 0, vid, pid)
    struct.pack_into("<I", payload, 4, 0x01020304)
    payload[8] = connect_mode
    payload[9] = battery
    payload[10] = charge
    encoded = bytes(b ^ 0xFF for b in payload)
    return bytes([0x00, 0x00]) + encoded


def test_xor_roundtrip():
    src = [0x00, 0x01, 0xAA, 0xFF]
    encoded = mchose_protocol.xor_encode(src)
    decoded = list(mchose_protocol.xor_decode(bytes(encoded)))

    assert decoded == src


def test_find_mchose_devices_dedup_and_sort(monkeypatch):
    monkeypatch.setattr(mchose_protocol, "IS_LINUX", True)
    monkeypatch.setattr(mchose_protocol, "ALL_VIDS", [0x1111, 0x2222])

    enumerated = {
        0x1111: [
            {"path": b"c", "usage_page": 0x0000, "interface_number": 3},
            {"path": b"a", "usage_page": 0xFF01, "interface_number": 2},
            {"path": b"a", "usage_page": 0xFF01, "interface_number": 2},
        ],
        0x2222: [
            {"path": b"b", "usage_page": 0xFF01, "interface_number": 1},
            {"path": b"x", "usage_page": 0x1234, "interface_number": 0},
        ],
    }
    monkeypatch.setattr(mchose_protocol, "hid", FakeHidModule(enumerated=enumerated))

    devices = mchose_protocol.find_mchose_devices()

    assert [d["path"] for d in devices] == [b"b", b"a", b"c"]


def test_find_wired_mchose_prefers_ff01(monkeypatch):
    monkeypatch.setattr(mchose_protocol, "ALL_VIDS", [0x9999])
    enumerated = {
        0x9999: [
            {"path": b"fallback", "usage_page": 0x0001, "product_string": "Mouse"},
            {"path": b"preferred", "usage_page": 0xFF01, "product_string": "Mouse Preferred"},
        ]
    }
    monkeypatch.setattr(mchose_protocol, "hid", FakeHidModule(enumerated=enumerated))

    wired = mchose_protocol.find_wired_mchose()

    assert wired == {"name": "Mouse Preferred", "path": b"preferred"}


def test_query_battery_success_and_validation_paths(monkeypatch):
    monkeypatch.setattr(mchose_protocol.time, "sleep", lambda _d: None)

    fake = FakeMchoseDevice(_build_status_frame(battery=88, charge=0, connect_mode=2))
    monkeypatch.setattr(mchose_protocol, "hid", FakeHidModule(device=fake))

    resp = mchose_protocol.query_battery(b"hid0")

    assert resp is not None
    assert resp["battery_level"] == 88
    assert resp["charge_status"] == 0
    assert resp["connect_mode"] == 2
    assert fake.opened == b"hid0"
    assert fake.sent[0] == mchose_protocol.REPORT_ID
    assert fake.closed is True

    # Invalid: VID/PID decode to 0.
    fake_zero = FakeMchoseDevice(_build_status_frame(vid=0, pid=0))
    monkeypatch.setattr(mchose_protocol, "hid", FakeHidModule(device=fake_zero))
    assert mchose_protocol.query_battery(b"hid0") is None

    # Invalid: battery > 100 should be rejected.
    fake_bad_battery = FakeMchoseDevice(_build_status_frame(battery=130))
    monkeypatch.setattr(mchose_protocol, "hid", FakeHidModule(device=fake_bad_battery))
    assert mchose_protocol.query_battery(b"hid0") is None


def test_resolve_model_from_response_known_and_unknown():
    known_pid = next(iter(mchose_protocol.MOUSE_DB.values()))["inner_pid"]

    assert mchose_protocol.resolve_model_from_response({"pid": known_pid}) is not None
    assert mchose_protocol.resolve_model_from_response({"pid": 0xDEAD}) is None
