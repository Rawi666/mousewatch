import json
import os
import shutil
import subprocess
import sys

try:
    from .mw_platform import IS_WINDOWS
except ImportError:
    from mw_platform import IS_WINDOWS

DEFAULTS = {
    "threshold": 20,
    "reminder_interval": 300,
    "poll_interval": 300,
    "notification_sound": True,
    "device_notifications": True,
    "start_with_windows": False,
}


def _coerce_bool(value, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return default


def _coerce_int(value, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, parsed))


def sanitize_settings(settings: dict | None) -> dict:
    """Normalize persisted settings into safe, clamped runtime values."""
    src = settings if isinstance(settings, dict) else {}
    return {
        "threshold": _coerce_int(src.get("threshold"), DEFAULTS["threshold"], 1, 100),
        "reminder_interval": _coerce_int(src.get("reminder_interval"), DEFAULTS["reminder_interval"], 60, 3600),
        "poll_interval": _coerce_int(src.get("poll_interval"), DEFAULTS["poll_interval"], 20, 3600),
        "notification_sound": _coerce_bool(src.get("notification_sound"), DEFAULTS["notification_sound"]),
        "device_notifications": _coerce_bool(src.get("device_notifications"), DEFAULTS["device_notifications"]),
        "start_with_windows": _coerce_bool(src.get("start_with_windows"), DEFAULTS["start_with_windows"]),
    }


def _xdg_base(env_name: str, fallback_parts: tuple[str, ...]) -> str:
    base = os.environ.get(env_name)
    if base:
        return base
    return os.path.join(os.path.expanduser("~"), *fallback_parts)


def _config_dir() -> str:
    if IS_WINDOWS:
        base = os.environ.get("LOCALAPPDATA", ".")
        return os.path.join(base, "MouseWatch")
    xdg_config = _xdg_base("XDG_CONFIG_HOME", (".config",))
    return os.path.join(xdg_config, "mousewatch")


def _config_path() -> str:
    return os.path.join(_config_dir(), "settings.json")


def load_settings() -> dict:
    """Load settings from JSON config file, falling back to defaults."""
    try:
        with open(_config_path(), "r") as f:
            saved = json.load(f)
    except (json.JSONDecodeError, OSError):
        saved = {}
    return sanitize_settings(saved)


def save_settings(settings: dict):
    """Save settings to JSON config file."""
    normalized = sanitize_settings(settings)
    os.makedirs(_config_dir(), exist_ok=True)
    with open(_config_path(), "w") as f:
        json.dump(normalized, f, indent=2)


def _ps_quote(value: str) -> str:
    # Escape single quotes for PowerShell single-quoted literals.
    return "'" + value.replace("'", "''") + "'"


def _startup_shortcut_path() -> str:
    if IS_WINDOWS:
        return os.path.join(
            os.environ.get("APPDATA", "."),
            "Microsoft", "Windows", "Start Menu", "Programs", "Startup",
            "MouseWatch.lnk",
        )
    xdg_config = _xdg_base("XDG_CONFIG_HOME", (".config",))
    return os.path.join(
        xdg_config,
        "autostart",
        "mousewatch.desktop",
    )


def _linux_applications_shortcut_path() -> str:
    xdg_data = _xdg_base("XDG_DATA_HOME", (".local", "share"))
    return os.path.join(xdg_data, "applications", "mousewatch.desktop")


def startup_shortcut_exists() -> bool:
    return os.path.lexists(_startup_shortcut_path())


def set_startup(enabled: bool):
    """Create or remove login startup entry for the current platform."""
    lnk_path = _startup_shortcut_path()
    if not enabled:
        if os.path.lexists(lnk_path):
            os.remove(lnk_path)
        return

    if IS_WINDOWS:
        if getattr(sys, "frozen", False):
            target = sys.executable
            arguments = ""
        else:
            target = sys.executable
            arguments = f'"{os.path.abspath(sys.argv[0])}"'

        ps_script = (
            f"$ws = New-Object -ComObject WScript.Shell; "
            f"$sc = $ws.CreateShortcut({_ps_quote(lnk_path)}); "
            f"$sc.TargetPath = {_ps_quote(target)}; "
            f"$sc.Arguments = {_ps_quote(arguments)}; "
            f"$sc.Save()"
        )
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_script],
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            check=False,
        )
        return

    os.makedirs(os.path.dirname(lnk_path), exist_ok=True)
    app_launcher_path = _linux_applications_shortcut_path()
    os.makedirs(os.path.dirname(app_launcher_path), exist_ok=True)

    if getattr(sys, "frozen", False):
        exec_cmd = f'"{sys.executable}" --autostart'
    else:
        script_path = os.path.abspath(sys.argv[0])
        exec_cmd = f'"{sys.executable}" "{script_path}" --autostart'

    desktop = "\n".join([
        "[Desktop Entry]",
        "Type=Application",
        "Version=1.0",
        "Name=MouseWatch",
        "Comment=MCHOSE battery monitor",
        f"TryExec={sys.executable}",
        f"Exec={exec_cmd}",
        "X-GNOME-Autostart-enabled=true",
        "StartupNotify=false",
        "Terminal=false",
        "",
    ])
    with open(app_launcher_path, "w", encoding="utf-8") as f:
        f.write(desktop)

    if os.path.lexists(lnk_path):
        os.remove(lnk_path)

    try:
        os.symlink(app_launcher_path, lnk_path)
    except OSError:
        shutil.copyfile(app_launcher_path, lnk_path)
