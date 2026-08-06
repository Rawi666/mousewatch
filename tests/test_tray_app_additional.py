import threading
from types import SimpleNamespace

import mousewatch.tray_app as tray_mod
from mousewatch.tray_app import TrayApp


class DummyProtocol:
    input_section_title = "Input"

    def format_model_name(self, model):
        return f"Protocol {model}"

    def status_from_response(self, resp):
        return resp["battery_level"], bool(resp.get("charge_status", 0))

    def format_status_text(self, model, level, charging):
        return f"{model} - {level}% ({'Charging' if charging else 'Wireless'})"


class FakeIcon:
    HAS_MENU = True

    def __init__(self):
        self.icon = None
        self.title = ""
        self.notified = []
        self.stopped = False

    def notify(self, message, title=""):
        self.notified.append((title, message))

    def stop(self):
        self.stopped = True


class FakeThread:
    created = []

    def __init__(self, target=None, daemon=None):
        self.target = target
        self.daemon = daemon
        self.started = False
        FakeThread.created.append(self)

    def start(self):
        self.started = True



def _settings():
    return {
        "threshold": 20,
        "poll_interval": 300,
        "reminder_interval": 300,
        "notification_sound": True,
        "device_notifications": True,
        "start_with_windows": False,
    }


def _build_app():
    return TrayApp(DummyProtocol(), "A9 Plus", b"path", {"battery_level": 50, "charge_status": 0}, _settings())


def test_create_menu_returns_none_when_menu_disabled():
    app = _build_app()
    app._menu_supported = False

    assert app._create_menu() is None


def test_update_ui_status_selects_known_or_unknown_icon(monkeypatch):
    app = _build_app()
    app.icon = FakeIcon()

    monkeypatch.setattr(tray_mod, "create_windows_battery_icon", lambda level, threshold: ("known", level, threshold))
    monkeypatch.setattr(tray_mod, "create_windows_unknown_battery_icon", lambda: "unknown")

    app.device_online = True
    app.level = 42
    app.threshold = 19
    app.status_text = "online"
    app._update_ui_status()
    assert app.icon.icon == ("known", 42, 19)
    assert app.icon.title == "online"

    app.device_online = False
    app.status_text = "offline"
    app._update_ui_status()
    assert app.icon.icon == "unknown"
    assert app.icon.title == "offline"


def test_notify_prefers_icon_notify_on_windows(monkeypatch):
    app = _build_app()
    app.icon = FakeIcon()

    monkeypatch.setattr(tray_mod, "IS_WINDOWS", True)
    safe_called = []
    monkeypatch.setattr(tray_mod, "safe_notify", lambda *args, **kwargs: safe_called.append((args, kwargs)) or True)

    app._notify("Title", "Body")

    assert app.icon.notified == [("Title", "Body")]
    assert safe_called == []


def test_notify_falls_back_to_safe_notify_when_icon_notify_fails(monkeypatch):
    app = _build_app()

    class BadIcon(FakeIcon):
        def notify(self, message, title=""):
            raise RuntimeError("notify failed")

    app.icon = BadIcon()
    monkeypatch.setattr(tray_mod, "IS_WINDOWS", True)

    calls = []
    monkeypatch.setattr(tray_mod, "safe_notify", lambda title, message, sound=True: calls.append((title, message, sound)) or True)

    app._notify("X", "Y")

    assert calls == [("X", "Y", True)]


def test_on_status_skips_when_refresh_already_active(monkeypatch):
    app = _build_app()
    app._status_refresh_active = True

    created = []
    monkeypatch.setattr(tray_mod.threading, "Thread", lambda *args, **kwargs: created.append((args, kwargs)))

    app._on_status(None, None)

    assert created == []


def test_on_status_starts_refresh_thread(monkeypatch):
    app = _build_app()
    notifications = []
    monkeypatch.setattr(app, "_refresh_status", lambda: "ok")
    monkeypatch.setattr(app, "_notify", lambda title, msg: notifications.append((title, msg)))
    monkeypatch.setattr(tray_mod.threading, "Thread", FakeThread)

    app._on_status(None, None)

    assert len(FakeThread.created) >= 1
    thread = FakeThread.created[-1]
    assert thread.started is True
    # Execute worker directly to assert side effects.
    thread.target()
    assert notifications == [("MouseWatch", "ok")]


def test_on_quit_direct_stops_icon_and_dispatcher():
    app = _build_app()
    app.icon = FakeIcon()
    stopped = []
    app._ui_dispatcher = SimpleNamespace(stop=lambda: stopped.append(True))

    app._on_quit_direct()

    assert app._stop_event.is_set()
    assert app._poll_interrupt.is_set()
    assert stopped == [True]
    assert app.icon.stopped is True


def test_run_creates_icon_threads_and_starts_event_loop(monkeypatch):
    app = _build_app()

    monkeypatch.setattr(tray_mod, "create_windows_battery_icon", lambda level, threshold: (level, threshold))
    monkeypatch.setattr(tray_mod, "create_windows_unknown_battery_icon", lambda: "unknown")
    monkeypatch.setattr(tray_mod, "IS_LINUX", False)

    class FakePystrayModule:
        class Menu:
            def __init__(self, *items):
                self.items = items

        class MenuItem:
            def __init__(self, text, callback, default=False):
                self.text = text
                self.callback = callback
                self.default = default

        class Icon:
            HAS_MENU = True

            def __init__(self, name, image, title="", menu=None):
                self.name = name
                self.icon = image
                self.title = title
                self.menu = menu
                self.ran = False

            def run(self):
                self.ran = True

            def stop(self):
                return None

    monkeypatch.setitem(__import__("sys").modules, "pystray", FakePystrayModule)
    monkeypatch.setattr(tray_mod.threading, "Thread", FakeThread)
    monkeypatch.setattr(app, "_install_windows_click_refresh", lambda: None)

    before = len(FakeThread.created)
    app.run()

    assert app.icon is not None
    assert app.icon.ran is True
    assert len(FakeThread.created) >= before + 3
