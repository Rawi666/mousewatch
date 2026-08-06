from types import SimpleNamespace

import pytest

import mousewatch.mousewatch as mousewatch_mod


class FakeProtocol:
    def __init__(self, key="atk", display_name="ATK"):
        self.key = key
        self.display_name = display_name
        self.input_section_title = "Input"
        self.calls = 0

    def format_model_name(self, model):
        return f"{self.display_name} {model}"

    def status_from_response(self, resp):
        return resp["battery_level"], bool(resp.get("charge_status", 0))

    def query_battery(self, _hid_path):
        self.calls += 1
        if self.calls == 1:
            return {"battery_level": 10, "charge_status": 0}
        return {"battery_level": 25, "charge_status": 0}

    def discover_devices(self):
        return []

    def autodetect(self, _common):
        return None

    def is_known_model(self, model):
        return model.lower() in {"a9 plus", "l7"}

    def list_models(self):
        return ["A9 Plus", "L7"]

    def pick_model(self):
        return "A9 Plus"



def _args(**overrides):
    base = {
        "threshold": 20,
        "interval": 1,
        "once": True,
        "nogui": True,
        "autostart": False,
        "probe": False,
        "model": None,
        "protocol": "auto",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_run_cli_once_triggers_low_battery_notify(monkeypatch, capsys):
    protocol = FakeProtocol()
    notified = []
    monkeypatch.setattr(mousewatch_mod, "safe_notify", lambda title, msg: notified.append((title, msg)) or True)
    monkeypatch.setattr(mousewatch_mod.time, "strftime", lambda _fmt: "09:00:00")

    mousewatch_mod.run_cli(protocol, "A9 Plus", b"path", _args(threshold=15, once=True))

    output = capsys.readouterr().out
    assert "LOW BATTERY ALERT" in output
    assert len(notified) == 1
    assert notified[0][0] == "MouseWatch - Low Battery"


def test_run_probe_returns_one_when_no_devices(capsys):
    protocol = FakeProtocol()

    code = mousewatch_mod.run_probe(protocol)

    out = capsys.readouterr().out
    assert code == 1
    assert "No candidate HID devices found" in out


def test_run_probe_prints_query_results(monkeypatch, capsys):
    protocol = FakeProtocol()
    protocol.discover_devices = lambda: [
        {
            "path": b"p",
            "product_string": "ATK NANO",
            "product_id": 0x10C9,
            "usage_page": 0x000C,
            "usage": 0x0001,
            "interface_number": 1,
        }
    ]
    monkeypatch.setattr(
        mousewatch_mod.Common,
        "query_after_throwaway",
        staticmethod(lambda _protocol, _path, settle_delay=0.05: {"battery_level": 60, "charge_status": 1, "raw_frame": [1, 2, 3]}),
    )

    code = mousewatch_mod.run_probe(protocol)

    out = capsys.readouterr().out
    assert code == 0
    assert "query: battery=60% charging=True" in out
    assert "frame: 01 02 03" in out


def test_main_unknown_protocol_exits(monkeypatch, capsys):
    monkeypatch.setattr(mousewatch_mod, "load_settings", lambda: {"threshold": 20, "poll_interval": 300})
    monkeypatch.setattr(mousewatch_mod, "sanitize_settings", lambda s: {
        "threshold": s.get("threshold", 20),
        "poll_interval": s.get("poll_interval", 300),
        "reminder_interval": 300,
        "notification_sound": True,
        "device_notifications": True,
        "start_with_windows": False,
    })
    monkeypatch.setattr(mousewatch_mod, "get_protocol_by_key", lambda _k: None)
    monkeypatch.setattr(mousewatch_mod, "get_protocol_keys", lambda: ["mchose", "atk"])
    monkeypatch.setattr(mousewatch_mod, "get_protocol_order", lambda _k: [])
    monkeypatch.setattr(
        mousewatch_mod.argparse.ArgumentParser,
        "parse_args",
        lambda self: _args(protocol="badproto", probe=False),
    )

    with pytest.raises(SystemExit) as exc:
        mousewatch_mod.main()

    assert exc.value.code == 1
    assert "Unknown protocol" in capsys.readouterr().out


def test_main_probe_with_selected_protocol_exits_with_probe_code(monkeypatch):
    protocol = FakeProtocol(key="atk", display_name="ATK")

    monkeypatch.setattr(mousewatch_mod, "load_settings", lambda: {"threshold": 20, "poll_interval": 300})
    monkeypatch.setattr(mousewatch_mod, "sanitize_settings", lambda s: {
        "threshold": s.get("threshold", 20),
        "poll_interval": s.get("poll_interval", 300),
        "reminder_interval": 300,
        "notification_sound": True,
        "device_notifications": True,
        "start_with_windows": False,
    })
    monkeypatch.setattr(mousewatch_mod, "get_protocol_by_key", lambda _k: protocol)
    monkeypatch.setattr(mousewatch_mod, "get_protocol_order", lambda _k: [protocol])
    monkeypatch.setattr(mousewatch_mod, "run_probe", lambda _p: 7)
    monkeypatch.setattr(
        mousewatch_mod.argparse.ArgumentParser,
        "parse_args",
        lambda self: _args(protocol="atk", probe=True),
    )

    with pytest.raises(SystemExit) as exc:
        mousewatch_mod.main()

    assert exc.value.code == 7


def test_main_once_mode_calls_run_cli_with_settings(monkeypatch):
    protocol = FakeProtocol(key="atk", display_name="ATK")
    called = {}

    monkeypatch.setattr(mousewatch_mod, "load_settings", lambda: {
        "threshold": 21,
        "poll_interval": 123,
        "reminder_interval": 400,
        "notification_sound": True,
        "device_notifications": True,
        "start_with_windows": False,
    })
    monkeypatch.setattr(mousewatch_mod, "sanitize_settings", lambda s: s)
    monkeypatch.setattr(mousewatch_mod, "get_protocol_by_key", lambda _k: protocol)
    monkeypatch.setattr(mousewatch_mod, "get_protocol_keys", lambda: ["atk"])
    monkeypatch.setattr(mousewatch_mod, "get_protocol_order", lambda _k: [protocol])
    monkeypatch.setattr(mousewatch_mod, "autodetect_any", lambda _common, _protocols: (protocol, "A9 Plus", b"p", {"battery_level": 51, "charge_status": 0}))

    def fake_run_cli(p, model, hid_path, args):
        called["protocol"] = p
        called["model"] = model
        called["hid_path"] = hid_path
        called["threshold"] = args.threshold
        called["interval"] = args.interval

    monkeypatch.setattr(mousewatch_mod, "run_cli", fake_run_cli)
    monkeypatch.setattr(
        mousewatch_mod.argparse.ArgumentParser,
        "parse_args",
        lambda self: _args(protocol="atk", once=True, nogui=False, threshold=None, interval=None),
    )

    mousewatch_mod.main()

    assert called["protocol"] is protocol
    assert called["model"] == "A9 Plus"
    assert called["hid_path"] == b"p"
    assert called["threshold"] == 21
    assert called["interval"] == 123
