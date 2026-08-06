import os
from pathlib import Path

import mousewatch.settings_store as settings_store


def test_coerce_bool_variants():
    assert settings_store._coerce_bool(True, False) is True
    assert settings_store._coerce_bool(0, True) is False
    assert settings_store._coerce_bool(" yes ", False) is True
    assert settings_store._coerce_bool("OFF", True) is False
    assert settings_store._coerce_bool("unknown", True) is True


def test_coerce_int_clamps_and_defaults():
    assert settings_store._coerce_int("10", 1, 1, 100) == 10
    assert settings_store._coerce_int("-5", 1, 1, 100) == 1
    assert settings_store._coerce_int("999", 1, 1, 100) == 100
    assert settings_store._coerce_int("bad", 7, 1, 100) == 7


def test_xdg_base_uses_env_or_fallback(monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", "/tmp/custom-xdg")
    assert settings_store._xdg_base("XDG_CONFIG_HOME", (".config",)) == "/tmp/custom-xdg"

    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setattr(settings_store.os.path, "expanduser", lambda _v: "/home/tester")
    assert settings_store._xdg_base("XDG_CONFIG_HOME", (".config",)) == "/home/tester/.config"


def test_config_dir_and_path_for_windows_and_linux(monkeypatch):
    monkeypatch.setattr(settings_store, "IS_WINDOWS", True)
    monkeypatch.setenv("LOCALAPPDATA", "/tmp/localappdata")
    assert settings_store._config_dir() == "/tmp/localappdata/MouseWatch"
    assert settings_store._config_path().endswith("/MouseWatch/settings.json")

    monkeypatch.setattr(settings_store, "IS_WINDOWS", False)
    monkeypatch.setenv("XDG_CONFIG_HOME", "/tmp/xdg")
    assert settings_store._config_dir() == "/tmp/xdg/mousewatch"
    assert settings_store._config_path().endswith("/mousewatch/settings.json")


def test_ps_quote_escapes_single_quotes():
    quoted = settings_store._ps_quote("C:/O'Hare/test")
    assert quoted == "'C:/O''Hare/test'"


def test_startup_shortcut_exists_delegates_to_lexists(monkeypatch):
    monkeypatch.setattr(settings_store, "_startup_shortcut_path", lambda: "/tmp/shortcut")
    monkeypatch.setattr(settings_store.os.path, "lexists", lambda p: p == "/tmp/shortcut")

    assert settings_store.startup_shortcut_exists() is True


def test_set_startup_disabled_removes_existing(monkeypatch):
    removed = []
    monkeypatch.setattr(settings_store, "_startup_shortcut_path", lambda: "/tmp/shortcut")
    monkeypatch.setattr(settings_store.os.path, "lexists", lambda _p: True)
    monkeypatch.setattr(settings_store.os, "remove", lambda p: removed.append(p))

    settings_store.set_startup(False)

    assert removed == ["/tmp/shortcut"]


def test_set_startup_windows_runs_powershell(monkeypatch):
    monkeypatch.setattr(settings_store, "IS_WINDOWS", True)
    monkeypatch.setattr(settings_store, "_startup_shortcut_path", lambda: "C:/Users/Test/Start Menu/MouseWatch.lnk")
    monkeypatch.setattr(settings_store.sys, "executable", "C:/Python/python.exe")
    monkeypatch.setattr(settings_store.sys, "argv", ["mousewatch.py"], raising=False)
    monkeypatch.setattr(settings_store.sys, "frozen", False, raising=False)

    calls = []

    def fake_run(args, creationflags=0, check=False):
        calls.append({"args": args, "creationflags": creationflags, "check": check})
        return None

    monkeypatch.setattr(settings_store.subprocess, "run", fake_run)

    settings_store.set_startup(True)

    assert len(calls) == 1
    cmd = calls[0]["args"]
    assert cmd[:3] == ["powershell", "-NoProfile", "-Command"]
    script = cmd[3]
    assert "CreateShortcut" in script
    assert "MouseWatch.lnk" in script


def test_set_startup_linux_creates_launcher_and_symlink(monkeypatch, tmp_path):
    monkeypatch.setattr(settings_store, "IS_WINDOWS", False)
    monkeypatch.setattr(settings_store.sys, "frozen", False, raising=False)
    monkeypatch.setattr(settings_store.sys, "executable", "/usr/bin/python3")
    monkeypatch.setattr(settings_store.sys, "argv", ["./src/mousewatch/mousewatch.py"], raising=False)

    autostart = tmp_path / "autostart" / "mousewatch.desktop"
    launcher = tmp_path / "applications" / "mousewatch.desktop"

    monkeypatch.setattr(settings_store, "_startup_shortcut_path", lambda: str(autostart))
    monkeypatch.setattr(settings_store, "_linux_applications_shortcut_path", lambda: str(launcher))

    settings_store.set_startup(True)

    assert launcher.exists()
    assert autostart.exists()
    content = launcher.read_text(encoding="utf-8")
    assert "[Desktop Entry]" in content
    assert "Exec=\"/usr/bin/python3\"" in content


def test_set_startup_linux_falls_back_to_copy_when_symlink_fails(monkeypatch, tmp_path):
    monkeypatch.setattr(settings_store, "IS_WINDOWS", False)
    monkeypatch.setattr(settings_store.sys, "frozen", True, raising=False)
    monkeypatch.setattr(settings_store.sys, "executable", "/opt/MouseWatch")

    autostart = tmp_path / "autostart" / "mousewatch.desktop"
    launcher = tmp_path / "applications" / "mousewatch.desktop"

    monkeypatch.setattr(settings_store, "_startup_shortcut_path", lambda: str(autostart))
    monkeypatch.setattr(settings_store, "_linux_applications_shortcut_path", lambda: str(launcher))
    monkeypatch.setattr(settings_store.os, "symlink", lambda _src, _dst: (_ for _ in ()).throw(OSError("no symlink")))

    settings_store.set_startup(True)

    assert launcher.exists()
    assert autostart.exists()
    assert autostart.read_text(encoding="utf-8") == launcher.read_text(encoding="utf-8")
