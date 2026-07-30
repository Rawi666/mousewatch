import json

from mousewatch.settings_store import DEFAULTS, load_settings, sanitize_settings, save_settings


def test_sanitize_settings_clamps_and_coerces_types():
    raw = {
        "threshold": "999",
        "reminder_interval": "10",
        "poll_interval": "bad",
        "notification_sound": "yes",
        "device_notifications": 0,
        "start_with_windows": "false",
    }

    result = sanitize_settings(raw)

    assert result["threshold"] == 100
    assert result["reminder_interval"] == 60
    assert result["poll_interval"] == DEFAULTS["poll_interval"]
    assert result["notification_sound"] is True
    assert result["device_notifications"] is False
    assert result["start_with_windows"] is False


def test_load_settings_falls_back_to_defaults_on_invalid_json(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    config_dir = tmp_path / "mousewatch"
    config_dir.mkdir(parents=True)
    (config_dir / "settings.json").write_text("{invalid json", encoding="utf-8")

    result = load_settings()

    assert result == DEFAULTS


def test_save_settings_persists_sanitized_values(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    save_settings({
        "threshold": -20,
        "reminder_interval": 9999,
        "poll_interval": 25,
        "notification_sound": "off",
        "device_notifications": "1",
        "start_with_windows": "on",
    })

    path = tmp_path / "mousewatch" / "settings.json"
    saved = json.loads(path.read_text(encoding="utf-8"))

    assert saved["threshold"] == 1
    assert saved["reminder_interval"] == 3600
    assert saved["poll_interval"] == 25
    assert saved["notification_sound"] is False
    assert saved["device_notifications"] is True
    assert saved["start_with_windows"] is True
