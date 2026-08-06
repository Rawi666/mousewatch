import threading

from mousewatch.common import Common
import mousewatch.common as common_mod


class DummyProtocol:
    def __init__(self):
        self.calls = []

    def status_from_response(self, resp):
        return resp["battery_level"], bool(resp.get("charge_status", 0))

    def format_status_text(self, model, level, charging):
        status = "Charging" if charging else "Wireless"
        return f"{model} - {level}% ({status})"

    def format_model_name(self, model):
        return f"Model {model}"

    def append_debug_input_details(self, lines, decoded):
        lines.append(f"decoded-len={len(decoded)}")

    def query_battery(self, _path):
        self.calls.append("query")
        return None

    def discover_devices(self):
        return []


class AltProtocol(DummyProtocol):
    def __init__(self, detected):
        super().__init__()
        self._detected = detected

    def autodetect(self, _common_cls):
        return self._detected


class DummyApp(Common):
    def __init__(self):
        self.notifications = []
        self.ui_updates = 0

    def _notify(self, title, message):
        self.notifications.append((title, message))

    def _update_ui_status(self):
        self.ui_updates += 1


class FakePollInterrupt:
    def __init__(self):
        self.wait_calls = 0
        self.clear_calls = 0

    def wait(self, _timeout):
        self.wait_calls += 1
        return False

    def clear(self):
        self.clear_calls += 1

    def set(self):
        return None


class FakeProtocolForRecovery(DummyProtocol):
    def __init__(self, devices):
        super().__init__()
        self._devices = devices

    def discover_devices(self):
        return self._devices



def _base_settings():
    return {
        "threshold": 20,
        "poll_interval": 300,
        "reminder_interval": 300,
        "notification_sound": True,
        "device_notifications": True,
        "start_with_windows": False,
    }


def test_init_runtime_state_with_initial_response_sets_online_fields():
    app = DummyApp()
    protocol = DummyProtocol()

    Common.init_runtime_state(
        app,
        protocol,
        "A9 Plus",
        b"path",
        {"battery_level": 77, "charge_status": 1, "device_online": True},
        _base_settings(),
    )

    assert app.level == 77
    assert app.charging is True
    assert app.device_online is True
    assert app.status_text == "A9 Plus - 77% (Charging)"


def test_init_runtime_state_without_initial_response_sets_offline_defaults():
    app = DummyApp()
    protocol = DummyProtocol()

    Common.init_runtime_state(
        app,
        protocol,
        "A9 Plus",
        None,
        None,
        _base_settings(),
    )

    assert app.level == 0
    assert app.charging is False
    assert app.device_online is False
    assert app.status_text == "MouseWatch - Waiting for device"


def test_query_battery_retry_retries_until_success(monkeypatch):
    calls = {"n": 0}

    class RetryProtocol:
        def query_battery(self, _path):
            calls["n"] += 1
            if calls["n"] < 3:
                return None
            return {"battery_level": 50}

    sleeps = []
    monkeypatch.setattr(common_mod.time, "sleep", lambda d: sleeps.append(d))

    resp = Common.query_battery_retry(RetryProtocol(), b"x", retries=5, delay=0.25)

    assert resp == {"battery_level": 50}
    assert calls["n"] == 3
    assert sleeps == [0.25, 0.25]


def test_query_after_throwaway_queries_twice(monkeypatch):
    class P:
        def __init__(self):
            self.calls = 0

        def query_battery(self, _path):
            self.calls += 1
            return None if self.calls == 1 else {"battery_level": 42}

    p = P()
    sleeps = []
    monkeypatch.setattr(common_mod.time, "sleep", lambda d: sleeps.append(d))

    resp = Common.query_after_throwaway(p, b"path", settle_delay=0.05)

    assert resp == {"battery_level": 42}
    assert p.calls == 2
    assert sleeps == [0.05]


def test_apply_settings_to_app_sets_poll_interrupt_on_interval_change():
    app = DummyApp()
    Common.init_runtime_state(app, DummyProtocol(), "M", b"p", None, _base_settings())

    Common.apply_settings_to_app(
        app,
        {
            "threshold": 15,
            "poll_interval": 120,
            "reminder_interval": 180,
            "notification_sound": False,
            "device_notifications": False,
        },
    )

    assert app.threshold == 15
    assert app.interval == 120
    assert app.reminder_interval == 180
    assert app.notification_sound is False
    assert app.device_notifications is False
    assert app._poll_interrupt.is_set()


def test_build_debug_lines_with_and_without_input_data():
    app = DummyApp()
    protocol = DummyProtocol()
    Common.init_runtime_state(app, protocol, "ModelX", b"p", {"battery_level": 25, "charge_status": 0}, _base_settings())

    lines = Common.build_debug_lines(app, snapshot=None, section_title="Input Section")
    assert any("No input reports received yet." in line for line in lines)
    assert any("Manual refresh: no response" in line for line in lines)

    app._last_input_time = "12:00:00"
    app._last_input_raw = [1, 2, 3]
    app._last_input_decoded = [4, 5, 6]

    lines = Common.build_debug_lines(app, snapshot={"battery_level": 33}, section_title="Input Section")
    assert any("Raw:     01 02 03" in line for line in lines)
    assert any("Decoded: 04 05 06" in line for line in lines)
    assert any("decoded-len=3" in line for line in lines)
    assert any("Manual refresh: battery 33%" in line for line in lines)


def test_ordered_device_paths_deduplicates_preserving_order():
    app = DummyApp()
    Common.init_runtime_state(app, DummyProtocol(), "M", b"p", None, _base_settings())

    paths = app._ordered_device_paths([
        {"path": b"a"},
        {"path": b"b"},
        {"path": b"a"},
        {"path": b"c"},
    ])

    assert paths == [b"a", b"b", b"c"]
    assert app._pick_first_available_path([]) is None
    assert app._pick_first_available_path([{"path": b"x"}, {"path": b"y"}]) == b"x"


def test_recover_path_and_query_switches_to_candidate_path(monkeypatch):
    app = DummyApp()
    protocol = FakeProtocolForRecovery([{"path": b"old"}, {"path": b"new"}])
    Common.init_runtime_state(app, protocol, "M", b"old", None, _base_settings())

    monkeypatch.setattr(Common, "query_battery_retry", staticmethod(lambda *_args, **_kwargs: None))
    monkeypatch.setattr(
        Common,
        "query_after_throwaway",
        staticmethod(lambda _protocol, path, settle_delay=0.05: {"battery_level": 44} if path == b"new" else None),
    )

    resp = app._recover_path_and_query()

    assert resp == {"battery_level": 44}
    assert app.hid_path == b"new"


def test_recover_path_and_query_switches_protocol_on_autodetect(monkeypatch):
    app = DummyApp()
    current = FakeProtocolForRecovery([])
    alt = AltProtocol(("AltModel", b"alt", {"battery_level": 88, "charge_status": 1}))
    Common.init_runtime_state(
        app,
        current,
        "Current",
        b"old",
        None,
        _base_settings(),
        available_protocols=[current, alt],
    )

    app._last_input_raw = [1]
    app._last_input_decoded = [2]
    app._last_input_time = "12:34:56"

    monkeypatch.setattr(Common, "query_battery_retry", staticmethod(lambda *_args, **_kwargs: None))

    resp = app._recover_path_and_query()

    assert resp == {"battery_level": 88, "charge_status": 1}
    assert app.protocol is alt
    assert app.model == "AltModel"
    assert app.hid_path == b"alt"
    assert app._last_input_raw is None
    assert app._last_input_decoded is None
    assert app._last_input_time is None


def test_refresh_status_updates_state_on_success(monkeypatch):
    app = DummyApp()
    protocol = DummyProtocol()
    Common.init_runtime_state(app, protocol, "M", b"p", None, _base_settings())

    monkeypatch.setattr(app, "_recover_path_and_query", lambda retries=2, delay=0.2: {"battery_level": 61, "charge_status": 1})
    monkeypatch.setattr(common_mod.time, "strftime", lambda _fmt: "10:11:12")

    msg = app._refresh_status()

    assert app.device_online is True
    assert app.level == 61
    assert app.charging is True
    assert app.ui_updates == 1
    assert "Updated at 10:11:12" in msg


def test_refresh_status_handles_disconnected_state(monkeypatch):
    app = DummyApp()
    Common.init_runtime_state(app, DummyProtocol(), "M", b"p", None, _base_settings())

    monkeypatch.setattr(app, "_recover_path_and_query", lambda retries=2, delay=0.2: None)

    msg = app._refresh_status()

    assert msg == "No mouse detected. Waiting for device..."
    assert app.device_online is False
    assert app.ui_updates == 1


def test_full_and_low_battery_notifications(monkeypatch):
    app = DummyApp()
    protocol = DummyProtocol()
    Common.init_runtime_state(
        app,
        protocol,
        "M",
        b"p",
        {"battery_level": 100, "charge_status": 1},
        _base_settings(),
    )

    app._handle_full_charge_notification()
    assert app._notified_full is True
    assert app.notifications[-1][0] == "MouseWatch - Fully Charged"

    app.notifications.clear()
    app.level = 19
    app.charging = False
    app.threshold = 20
    app.reminder_interval = 300
    app._last_notify_time = 0
    monkeypatch.setattr(common_mod.time, "time", lambda: 1000.0)

    app._handle_low_battery_notification()
    assert app.notifications[-1][0] == "MouseWatch - Low Battery"
    assert app._last_notify_time == 1000.0

    app.notifications.clear()
    app.level = 50
    app._handle_low_battery_notification()
    assert app._last_notify_time == 0


def test_poll_loop_processes_success_then_stops(monkeypatch):
    app = DummyApp()
    Common.init_runtime_state(app, DummyProtocol(), "M", b"p", None, _base_settings())
    app._poll_interrupt = FakePollInterrupt()

    responses = [{"battery_level": 40, "charge_status": 0}]

    def fake_recover():
        app._stop_event.set()
        return responses.pop(0)

    monkeypatch.setattr(app, "_recover_path_and_query", fake_recover)

    app._poll_loop()

    assert app.level == 40
    assert app.device_online is True
    assert app.ui_updates == 1
    assert app._poll_interrupt.clear_calls == 1
