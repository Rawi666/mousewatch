import threading
from types import SimpleNamespace

import mousewatch.debug_window as debug_window_mod
import mousewatch.settings_window as settings_window_mod
import mousewatch.qt_debug_dialog as qt_debug_mod
import mousewatch.qt_settings_dialog as qt_settings_mod
import mousewatch.qt_tray_app as qt_tray_mod


class _Getter:
    def __init__(self, value):
        self._value = value

    def get(self):
        return self._value


class _TextSink:
    def __init__(self):
        self.ops = []
        self.value = ""

    def config(self, **kwargs):
        self.ops.append(("config", kwargs))

    def delete(self, *_args):
        self.ops.append(("delete", _args))

    def insert(self, *_args):
        self.value = _args[1]
        self.ops.append(("insert", _args))



def test_settings_window_open_returns_existing_instance(monkeypatch):
    class GoodWindow:
        def __init__(self):
            self.lift_calls = 0
            self.focus_calls = 0

        def lift(self):
            self.lift_calls += 1

        def focus_force(self):
            self.focus_calls += 1

    existing = SimpleNamespace(_window=GoodWindow())
    settings_window_mod.SettingsWindow._instance = existing

    out = settings_window_mod.SettingsWindow.open(object(), object())

    assert out is existing
    assert existing._window.lift_calls == 1
    assert existing._window.focus_calls == 1


def test_settings_window_on_save_and_on_close(monkeypatch):
    captured = []
    monkeypatch.setattr(settings_window_mod.Common, "persist_and_apply_settings", lambda app, settings: captured.append((app, settings)))

    win = settings_window_mod.SettingsWindow.__new__(settings_window_mod.SettingsWindow)
    win._tray_app = "tray"
    win._threshold_var = _Getter(11)
    win._reminder_var = _Getter(120)
    win._poll_var = _Getter(90)
    win._sound_var = _Getter(False)
    win._devnotify_var = _Getter(True)
    win._startup_var = _Getter(True)
    win._on_close_called = False
    win._on_close = lambda: setattr(win, "_on_close_called", True)

    settings_window_mod.SettingsWindow._on_save(win)

    assert len(captured) == 1
    assert captured[0][0] == "tray"
    assert captured[0][1]["threshold"] == 11
    assert win._on_close_called is True

    closable = settings_window_mod.SettingsWindow.__new__(settings_window_mod.SettingsWindow)
    destroyed = []
    closable._window = SimpleNamespace(destroy=lambda: destroyed.append(True))
    settings_window_mod.SettingsWindow._instance = closable

    settings_window_mod.SettingsWindow._on_close(closable)

    assert settings_window_mod.SettingsWindow._instance is None
    assert destroyed == [True]


def test_debug_window_open_existing_and_refresh(monkeypatch):
    class ExistingWindow:
        def __init__(self):
            self.lifted = 0
            self.focused = 0

        def lift(self):
            self.lifted += 1

        def focus_force(self):
            self.focused += 1

    refreshed = []
    existing = SimpleNamespace(_window=ExistingWindow(), _refresh=lambda: refreshed.append(True))
    debug_window_mod.DebugWindow._instance = existing

    out = debug_window_mod.DebugWindow.open(object(), object())

    assert out is existing
    assert refreshed == [True]

    sink = _TextSink()
    app = SimpleNamespace(
        refresh_debug_snapshot=lambda: {"battery_level": 66},
        protocol=SimpleNamespace(input_section_title="Input Section"),
    )

    monkeypatch.setattr(
        debug_window_mod.Common,
        "build_debug_lines",
        lambda _app, _snapshot, section_title="": [section_title, "line2"],
    )

    dbg = debug_window_mod.DebugWindow.__new__(debug_window_mod.DebugWindow)
    dbg._tray_app = app
    dbg._text = sink

    debug_window_mod.DebugWindow._refresh(dbg)

    assert sink.value == "── Input Section ──\nline2"


def test_debug_window_on_close_clears_singleton():
    dbg = debug_window_mod.DebugWindow.__new__(debug_window_mod.DebugWindow)
    destroyed = []
    dbg._window = SimpleNamespace(destroy=lambda: destroyed.append(True))
    debug_window_mod.DebugWindow._instance = dbg

    debug_window_mod.DebugWindow._on_close(dbg)

    assert debug_window_mod.DebugWindow._instance is None
    assert destroyed == [True]


def test_qt_settings_dialog_on_save_unbound(monkeypatch):
    captured = []
    monkeypatch.setattr(qt_settings_mod.Common, "persist_and_apply_settings", lambda app, settings: captured.append((app, settings)))

    fake_self = SimpleNamespace(
        _tray_app="tray",
        _threshold_spin=SimpleNamespace(value=lambda: 13),
        _reminder_spin=SimpleNamespace(value=lambda: 300),
        _poll_spin=SimpleNamespace(value=lambda: 90),
        _sound_check=SimpleNamespace(isChecked=lambda: True),
        _device_check=SimpleNamespace(isChecked=lambda: False),
        _startup_check=SimpleNamespace(isChecked=lambda: True),
        closed=False,
    )
    fake_self.close = lambda: setattr(fake_self, "closed", True)

    qt_settings_mod.QtSettingsDialog._on_save(fake_self)

    assert captured[0][0] == "tray"
    assert captured[0][1]["threshold"] == 13
    assert fake_self.closed is True


def test_qt_debug_dialog_refresh_unbound(monkeypatch):
    text_sink = SimpleNamespace(value="", setPlainText=lambda text: setattr(text_sink, "value", text))
    app = SimpleNamespace(
        refresh_debug_snapshot=lambda: {"battery_level": 70},
        protocol=SimpleNamespace(input_section_title="ATK Input"),
    )

    monkeypatch.setattr(qt_debug_mod.Common, "build_debug_lines", lambda _app, _snapshot, section_title="": [section_title, "L2"])

    fake_self = SimpleNamespace(_tray_app=app, _text=text_sink)

    qt_debug_mod.QtDebugDialog.refresh(fake_self)

    assert text_sink.value == "ATK Input\nL2"


def test_qt_tray_methods_unbound(monkeypatch):
    icon_calls = []
    monkeypatch.setattr(qt_tray_mod, "create_qt_battery_icon", lambda level, threshold: ("known", level, threshold))
    monkeypatch.setattr(qt_tray_mod, "create_qt_unknown_battery_icon", lambda: "unknown")

    tray = SimpleNamespace(
        setIcon=lambda icon: icon_calls.append(("icon", icon)),
        setToolTip=lambda tip: icon_calls.append(("tip", tip)),
        setVisible=lambda visible: icon_calls.append(("visible", visible)),
        hide=lambda: icon_calls.append(("hide", True)),
    )

    fake = SimpleNamespace(
        level=55,
        charging=False,
        status_text="status",
        threshold=20,
        device_online=True,
        tray=tray,
    )

    qt_tray_mod.QtTrayApp._apply_status(fake, 10, True, "new")
    assert fake.level == 10
    assert fake.charging is True
    assert fake.status_text == "new"
    assert ("icon", ("known", 10, 20)) in icon_calls

    emitted = []
    fake2 = SimpleNamespace(level=7, charging=False, status_text="s", status_changed=SimpleNamespace(emit=lambda *args: emitted.append(args)))
    qt_tray_mod.QtTrayApp._update_ui_status(fake2)
    assert emitted == [(7, False, "s")]

    notifications = []
    lock = threading.Lock()
    fake3 = SimpleNamespace(
        _status_refresh_lock=lock,
        _status_refresh_active=False,
        _refresh_status=lambda: "refreshed",
        _notify=lambda title, msg: notifications.append((title, msg)),
    )

    class ImmediateThread:
        def __init__(self, target=None, daemon=None):
            self.target = target
            self.daemon = daemon

        def start(self):
            self.target()

    monkeypatch.setattr(qt_tray_mod.threading, "Thread", ImmediateThread)
    qt_tray_mod.QtTrayApp._on_status(fake3)
    assert notifications == [("MouseWatch", "refreshed")]

    stop_event = threading.Event()
    poll_interrupt = threading.Event()
    quit_calls = []
    fake4 = SimpleNamespace(
        _stop_event=stop_event,
        _poll_interrupt=poll_interrupt,
        tray=SimpleNamespace(hide=lambda: quit_calls.append("hide")),
        _app=SimpleNamespace(quit=lambda: quit_calls.append("quit")),
    )
    qt_tray_mod.QtTrayApp._on_quit(fake4)
    assert stop_event.is_set()
    assert poll_interrupt.is_set()
    assert quit_calls == ["hide", "quit"]
