"""
MouseWatch - Battery monitor for MCHOSE wireless mice.

Polls battery level via HID and shows status in the system tray.
Low battery triggers a Windows toast notification.

Protocol reverse-engineered from the MCHOSE WebHID configurator.
"""

import argparse
import json
import os
import shutil
import struct
import subprocess
import sys
import threading
import time
from io import BytesIO

try:
    if sys.platform.startswith("linux"):
        import hidraw as hid
        HID_BACKEND = "hidraw"
    else:
        import hid
        HID_BACKEND = "hid"
except ImportError:
    import hid
    HID_BACKEND = "hid"

IS_WINDOWS = sys.platform.startswith("win")
IS_LINUX = sys.platform.startswith("linux")

if not IS_WINDOWS:
    from PySide6.QtCore import QObject, Qt, QTimer, Signal
    from PySide6.QtGui import QAction, QIcon, QImage, QPixmap
    from PySide6.QtWidgets import (
        QApplication,
        QCheckBox,
        QDialog,
        QDialogButtonBox,
        QFormLayout,
        QHBoxLayout,
        QLabel,
        QMenu,
        QPlainTextEdit,
        QPushButton,
        QSpinBox,
        QSystemTrayIcon,
        QVBoxLayout,
    )

# ── Settings persistence ──────────────────────────────────────────────────

DEFAULTS = {
    "threshold": 20,
    "reminder_interval": 300,
    "poll_interval": 300,
    "notification_sound": True,
    "device_notifications": True,
    "start_with_windows": False,
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
    settings = dict(DEFAULTS)
    try:
        with open(_config_path(), "r") as f:
            saved = json.load(f)
        for key in DEFAULTS:
            if key in saved:
                settings[key] = saved[key]
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass
    return settings


def save_settings(settings: dict):
    """Save settings to JSON config file."""
    os.makedirs(_config_dir(), exist_ok=True)
    with open(_config_path(), "w") as f:
        json.dump(settings, f, indent=2)


# ── Startup shortcut management ──────────────────────────────────────────

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


def _startup_shortcut_exists() -> bool:
    return os.path.lexists(_startup_shortcut_path())


def _set_startup(enabled: bool):
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
            target = sys.executable  # python.exe
            arguments = f'"{os.path.abspath(sys.argv[0])}"'

        ps_script = (
            f"$ws = New-Object -ComObject WScript.Shell; "
            f"$sc = $ws.CreateShortcut('{lnk_path}'); "
            f"$sc.TargetPath = '{target}'; "
            f"$sc.Arguments = '{arguments}'; "
            f"$sc.Save()"
        )
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_script],
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            check=False,
        )
        return

    # XDG autostart for Linux desktop environments.
    # The app will wait for the system tray to become available during autostart.
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

    # Symlink keeps one canonical launcher file; copy is fallback for filesystems
    # or desktop setups that do not allow symlinks here.
    try:
        os.symlink(app_launcher_path, lnk_path)
    except OSError:
        shutil.copyfile(app_launcher_path, lnk_path)

# ── Device database ────────────────────────────────────────────────────────
# All known MCHOSE vendor IDs (dongles may use any of these)
ALL_VIDS = [0x3837, 0x41E4, 0x0BDA, 0x5253]

# inner_pid: the product ID the mouse reports about itself in the status
# response, used to identify the exact model when the dongle VID/PID is shared.
MOUSE_DB = {
    "M7":              {"inner_pid": 0x0020},
    "M7 Pro":          {"inner_pid": 0x0030},
    "M7 Ultra":        {"inner_pid": 0x0031},
    "L7":              {"inner_pid": 0x00C0},
    "L7 Pro":          {"inner_pid": 0x00B0},
    "L7 Pro+":         {"inner_pid": 0x4015},
    "L7 Ultra":        {"inner_pid": 0x00B1},
    "L7 Ultra+":       {"inner_pid": 0x4016},
    "A7":              {"inner_pid": 0x0070},
    "A7 Pro":          {"inner_pid": 0x0010},
    "A7 Ultra":        {"inner_pid": 0x0011},
    "A7 Ultra(RE)":    {"inner_pid": 0x4110},
    "A7 V2 Pro":       {"inner_pid": 0x4018},
    "A7 V2 Pro+":      {"inner_pid": 0x4023},
    "A7 V2 Ultra":     {"inner_pid": 0x4019},
    "A7 V2 Ultra+":    {"inner_pid": 0x4021},
    "A7X Ultra":       {"inner_pid": 0x4011},
    "K7 Ultra":        {"inner_pid": 0x4150},
    "A5 V2 Ultra":     {"inner_pid": 0x1101},
    "AX5 V2":          {"inner_pid": 0x4010},
    "G3 Ultra 8K":     {"inner_pid": 0x4762},
    "G3 Ultra 4K":     {"inner_pid": 0x4762},
}

# Usage page for MCHOSE vendor-specific HID interface.
USAGE_PAGES = [0xFF01]
_LINUX_FALLBACK_USAGE_PAGES = [0x0000]

# ── HID protocol constants ─────────────────────────────────────────────────
REPORT_ID = 0x11
CMD_GET_STATUS = 0x06


def xor_encode(data: list[int]) -> list[int]:
    return [b ^ 0xFF for b in data]


def xor_decode(data: bytes) -> bytes:
    return bytes(b ^ 0xFF for b in data)


# ── Device discovery ───────────────────────────────────────────────────────

def find_mchose_devices() -> list[dict]:
    """Enumerate HID devices and return likely MCHOSE battery-report interfaces."""
    results = []
    seen_paths = set()

    allowed_pages = set(USAGE_PAGES)
    if IS_LINUX:
        # Some Linux hidapi backends expose vendor pages as 0x0000.
        allowed_pages.update(_LINUX_FALLBACK_USAGE_PAGES)

    for vid in ALL_VIDS:
        for dev in hid.enumerate(vid):
            usage_page = dev.get("usage_page", 0)
            if usage_page in allowed_pages and dev["path"] not in seen_paths:
                seen_paths.add(dev["path"])
                results.append(dev)

    def _sort_key(d: dict) -> tuple:
        usage_page = d.get("usage_page", 0)
        iface = d.get("interface_number", 999)
        return (usage_page != 0xFF01, usage_page == 0x0000, iface)

    results.sort(key=_sort_key)
    return results


def find_wired_mchose() -> dict | None:
    """Check if a MCHOSE mouse is connected via USB cable (any usage page).

    Returns dict with 'name' and 'path' (FF01 usage page preferred), or None.
    """
    best = None
    for vid in ALL_VIDS:
        for dev in hid.enumerate(vid):
            name = dev.get("product_string") or ""
            usage_page = dev.get("usage_page", 0)
            if best is None:
                best = {"name": name or "MCHOSE", "path": dev["path"]}
            if usage_page == 0xFF01:
                return {"name": name or "MCHOSE", "path": dev["path"]}
    return best


def query_battery(path: bytes) -> dict | None:
    """
    Send the status command and parse the response.

    Returns dict with keys: vid, pid, fw_version, connect_mode,
    connect_status, battery_level, charge_status — or None on failure.
    """
    try:
        dev = hid.device()
        dev.open_path(path)
        dev.set_nonblocking(False)

        payload = [CMD_GET_STATUS] + [0x00] * 19
        encoded = xor_encode(payload)
        dev.send_feature_report([REPORT_ID] + encoded)

        time.sleep(0.05)

        raw = dev.get_feature_report(REPORT_ID, 21)
        dev.close()

        if not raw or len(raw) < 12:
            return None

        decoded = xor_decode(bytes(raw[2:]))

        vid, pid = struct.unpack_from("<HH", decoded, 0)

        # All-zero decoded data means the device returned 0xFF filler
        # (stale/invalid response). Reject it.
        if vid == 0 and pid == 0:
            return None

        fw_version = struct.unpack_from("<I", decoded, 4)[0]
        status_byte = decoded[8]
        connect_mode = status_byte & 0x07
        connect_status = (status_byte >> 3) & 0x01
        battery_level = decoded[9]
        charge_status = decoded[10]

        return {
            "vid": vid,
            "pid": pid,
            "fw_version": fw_version,
            "connect_mode": connect_mode,
            "connect_status": connect_status,
            "battery_level": battery_level,
            "charge_status": charge_status,
        }
    except Exception as e:
        err = str(e)
        print(f"  [!] HID error: {err}")
        return None


def resolve_model_from_response(resp: dict) -> str | None:
    """Match the inner PID from the status response to a model."""
    for name, info in MOUSE_DB.items():
        if resp["pid"] == info["inner_pid"]:
            return name
    return None


# ── Auto-detection ─────────────────────────────────────────────────────────

def autodetect() -> tuple[str, bytes, dict] | None:
    """
    Auto-detect a connected MCHOSE mouse.

    Returns (model_name, hid_path, status_response) or None.
    """
    devices = find_mchose_devices()
    if not devices:
        return None

    for dev in devices:
        # First read can return stale data; do a throwaway read then re-query.
        resp = Common.query_after_throwaway(dev["path"])
        if resp is None:
            continue

        model = resolve_model_from_response(resp)
        if model is None:
            name = (dev.get("product_string") or "").replace("MCHOSE ", "")
            if name:
                model = name

        if model is None:
            continue

        return model, dev["path"], resp

    return None


# ── User interaction (CLI mode) ───────────────────────────────────────────

def pick_model() -> str:
    """Let the user pick a mouse model from the list."""
    names = sorted(MOUSE_DB.keys())
    print("\nAvailable MCHOSE mouse models:\n")
    for i, name in enumerate(names, 1):
        print(f"  {i:2d}. {name}")
    print()
    while True:
        try:
            choice = input("Select model number: ").strip()
            idx = int(choice) - 1
            if 0 <= idx < len(names):
                return names[idx]
        except (ValueError, EOFError):
            pass
        print("Invalid selection, try again.")


# ── Desktop notifications ──────────────────────────────────────────────────

def notify_windows(title: str, message: str, sound: bool = True):
    """Show a desktop notification on supported platforms."""
    if IS_WINDOWS:
        from winotify import Notification, audio

        toast = Notification(
            app_id="MouseWatch",
            title=title,
            msg=message,
            duration="long",
        )
        toast.set_audio(audio.Default if sound else audio.Silent, loop=False)
        toast.show()
        return

    if IS_LINUX:
        # notify-send is widely available on Linux desktop environments.
        try:
            subprocess.run(["notify-send", title, message], check=False)
        except FileNotFoundError:
            print(f"{title}: {message}")
        return

    print(f"{title}: {message}")


def safe_notify(title: str, message: str, sound: bool = True):
    try:
        notify_windows(title, message, sound=sound)
    except Exception:
        pass


class Common:
    """Shared cross-platform app logic used by both tray implementations."""

    # Attributes provided by concrete tray app implementations.
    model: str
    hid_path: bytes
    threshold: int
    interval: int
    reminder_interval: int
    notification_sound: bool
    device_notifications: bool
    level: int
    charging: bool
    status_text: str
    _last_notify_time: float
    _notified_full: bool
    _stop_event: threading.Event
    _poll_interrupt: threading.Event
    _last_e2_raw: list[int] | None
    _last_e2_decoded: list[int] | None
    _last_e2_time: str | None
    _last_debug_refresh_time: str | None

    def _notify(self, title: str, message: str):
        raise NotImplementedError

    def _update_ui_status(self):
        raise NotImplementedError

    @staticmethod
    def startup_label() -> str:
        return "Start with Windows" if IS_WINDOWS else "Start on login"

    @staticmethod
    def status_from_response(resp: dict) -> tuple[int, bool]:
        level = resp["battery_level"]
        charging = (resp["charge_status"] != 0 or resp["connect_mode"] == 0)
        return level, charging

    @staticmethod
    def format_status_text(model: str, level: int, charging: bool) -> str:
        if level == 0 and charging:
            return f"MCHOSE {model} - Charging"
        status = "Charging" if charging else "Wireless"
        return f"MCHOSE {model} - {level}% ({status})"

    @staticmethod
    def query_battery_retry(hid_path: bytes, retries: int = 5, delay: float = 2.0) -> dict | None:
        resp = query_battery(hid_path)
        for _ in range(retries):
            if resp is not None:
                break
            time.sleep(delay)
            resp = query_battery(hid_path)
        return resp

    @staticmethod
    def query_after_throwaway(hid_path: bytes, settle_delay: float = 0.1) -> dict | None:
        query_battery(hid_path)
        time.sleep(settle_delay)
        return query_battery(hid_path)

    @staticmethod
    def apply_settings_to_app(app, settings: dict):
        app.threshold = settings["threshold"]
        app.reminder_interval = settings["reminder_interval"]
        app.notification_sound = settings["notification_sound"]
        app.device_notifications = settings["device_notifications"]
        if app.interval != settings["poll_interval"]:
            app.interval = settings["poll_interval"]
            app._poll_interrupt.set()

    @staticmethod
    def persist_and_apply_settings(app, settings: dict):
        save_settings(settings)
        Common.apply_settings_to_app(app, settings)
        _set_startup(settings["start_with_windows"])

    @staticmethod
    def build_debug_lines(app, snapshot: dict | None, section_title: str = "Last E2 Input Report") -> list[str]:
        lines = []
        lines.append(f"Model:   MCHOSE {app.model}")
        lines.append(f"Battery: {app.level}%")
        lines.append(f"Status:  {'Charging' if app.charging else 'Wireless'}")
        if app._last_debug_refresh_time:
            lines.append(f"Refreshed: {app._last_debug_refresh_time}")
        lines.append("")
        lines.append(section_title)

        if app._last_e2_time:
            lines.append(f"Time:    {app._last_e2_time}")
            raw = app._last_e2_raw
            dec = app._last_e2_decoded
            if raw is not None:
                lines.append(f"Raw:     {' '.join(f'{b:02X}' for b in raw)}")
            if dec is not None:
                lines.append(f"Decoded: {' '.join(f'{b:02X}' for b in dec)}")
                lines.append("")
                if len(dec) >= 6:
                    lines.append(f"  [0] Report ID:    0x{dec[0]:02X}")
                    lines.append(f"  [1] Notification: 0x{dec[1]:02X}")
                    lines.append(f"  [2] Sub-type hi:  0x{dec[2]:02X}")
                    lines.append(f"  [3] Sub-type lo:  0x{dec[3]:02X}")
                    lines.append(f"  [4] chargeStatus: {dec[4]}")
                    lines.append(f"  [5] batteryLevel: {dec[5]}%")
                    name_bytes = bytes(b for b in dec[8:] if 0x20 <= b < 0x7F)
                    if name_bytes:
                        lines.append(
                            f"  [8+] Model name:  {name_bytes.decode('ascii', errors='replace')}"
                        )
        else:
            lines.append("No E2 reports received yet.")

        lines.append("")
        if snapshot is None:
            lines.append("Manual refresh: no response")
        else:
            lines.append(f"Manual refresh: battery {snapshot['battery_level']}%")

        return lines

    def _status_text(self) -> str:
        return Common.format_status_text(self.model, self.level, self.charging)

    def apply_settings(self, settings: dict):
        Common.apply_settings_to_app(self, settings)

    def _refresh_status(self) -> str:
        resp = Common.query_battery_retry(self.hid_path)
        if resp is None:
            return "Failed to read battery status"

        self.level, self.charging = Common.status_from_response(resp)
        self.status_text = self._status_text()
        self._update_ui_status()
        return f"{self.status_text}\nUpdated at {time.strftime('%H:%M:%S')}"

    def refresh_debug_snapshot(self) -> dict | None:
        """Force a fresh HID read for the debug dialog and update visible state."""
        resp = Common.query_battery_retry(self.hid_path)
        self._last_debug_refresh_time = time.strftime("%H:%M:%S")
        if resp is None:
            return None

        self.level, self.charging = Common.status_from_response(resp)
        self.status_text = self._status_text()
        self._update_ui_status()
        return resp

    def _handle_full_charge_notification(self):
        if self.level == 100 and self.charging and not self._notified_full:
            self._notified_full = True
            self._notify(
                "MouseWatch - Fully Charged",
                f"MCHOSE {self.model} is fully charged",
            )
        elif not self.charging or self.level < 100:
            self._notified_full = False

    def _handle_low_battery_notification(self):
        now = time.time()
        if (self.level <= self.threshold and not self.charging
                and (now - self._last_notify_time) >= self.reminder_interval):
            self._last_notify_time = now
            self._notify(
                "MouseWatch - Low Battery",
                f"MCHOSE {self.model} battery is at {self.level}%",
            )
        elif self.level > self.threshold:
            self._last_notify_time = 0

    def _input_listener(self):
        while not self._stop_event.is_set():
            try:
                dev = hid.device()
                dev.open_path(self.hid_path)
                dev.set_nonblocking(False)
            except Exception:
                if self._stop_event.wait(5):
                    break
                continue

            try:
                while not self._stop_event.is_set():
                    raw = dev.read(64, timeout_ms=1000)
                    if not raw:
                        continue

                    decoded = xor_decode(bytes(raw))
                    self._last_e2_raw = list(raw)
                    self._last_e2_decoded = list(decoded)
                    self._last_e2_time = time.strftime("%H:%M:%S")

                    if len(decoded) < 6 or decoded[1] != 0xE2:
                        continue

                    charge_status = decoded[4]
                    battery_level = decoded[5]
                    if battery_level == 0 or battery_level > 100:
                        continue

                    old_charging = self.charging
                    self.level = battery_level
                    self.charging = charge_status != 0
                    self.status_text = self._status_text()
                    self._update_ui_status()

                    if self.charging != old_charging and self.device_notifications:
                        msg = (
                            f"MCHOSE {self.model} is charging ({self.level}%)"
                            if self.charging
                            else f"MCHOSE {self.model} unplugged ({self.level}%)"
                        )
                        self._notify("MouseWatch", msg)

                    self._handle_full_charge_notification()
            finally:
                try:
                    dev.close()
                except Exception:
                    pass
                if not self._stop_event.is_set():
                    self._stop_event.wait(2)

    def _device_watcher(self):
        known_paths = {d["path"] for d in find_mchose_devices()}
        while not self._stop_event.wait(5):
            current_paths = {d["path"] for d in find_mchose_devices()}
            if current_paths != known_paths:
                added = current_paths - known_paths
                removed = known_paths - current_paths
                known_paths = current_paths
                self._poll_interrupt.set()
                if self.device_notifications:
                    if added and removed:
                        msg = "Device reconnected"
                    elif added:
                        msg = "Device connected"
                    else:
                        msg = "Device disconnected"
                    self._notify("MouseWatch", msg)

    def _poll_loop(self):
        while True:
            self._poll_interrupt.wait(self.interval)
            if self._stop_event.is_set():
                break
            self._poll_interrupt.clear()

            resp = Common.query_battery_retry(self.hid_path)
            if resp is None:
                continue

            self.level, self.charging = Common.status_from_response(resp)
            self.status_text = self._status_text()
            self._update_ui_status()
            self._handle_full_charge_notification()
            self._handle_low_battery_notification()


# ── Icon generation ────────────────────────────────────────────────────────

def _battery_color(level: int, threshold: int) -> str:
    """Return hex color based on the configured battery threshold."""
    if level > threshold:
        return "#4CAF50"  # green
    return "#F44336"  # red


def _render_battery_icon(
    level: int,
    threshold: int,
    *,
    size: int,
    ring_box: list[int],
    ring_width: int,
    font_names: list[str],
    font_size_lt100: int,
    font_size_100: int,
    stroke_width: int,
    stroke_fill: tuple[int, int, int, int],
    target_size: int | None = None,
):
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    color = _battery_color(level, threshold)
    draw.ellipse(ring_box, outline=color, width=ring_width)

    text = str(level)
    font_size = font_size_lt100 if level < 100 else font_size_100
    font = None
    for font_name in font_names:
        try:
            font = ImageFont.truetype(font_name, font_size)
            break
        except OSError:
            continue
    if font is None:
        font = ImageFont.load_default()

    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    tx = (size - tw) // 2 - bbox[0]
    ty = (size - th) // 2 - bbox[1]
    draw.text(
        (tx, ty),
        text,
        fill=(255, 255, 255, 255),
        font=font,
        stroke_width=stroke_width,
        stroke_fill=stroke_fill,
    )

    if target_size and target_size != size:
        return img.resize((target_size, target_size), Image.Resampling.LANCZOS)
    return img


def create_battery_icon(level: int, threshold: int):
    """Generate a 64x64 PIL Image showing battery percentage in a colored ring."""
    size = 256
    return _render_battery_icon(
        level,
        threshold,
        size=size,
        ring_box=[32, 32, size - 33, size - 33],
        ring_width=4,
        font_names=["DejaVuSans-Bold.ttf", "arial.ttf"],
        font_size_lt100=116,
        font_size_100=92,
        stroke_width=3,
        stroke_fill=(0, 0, 0, 220),
        target_size=64,
    )


if not IS_WINDOWS:
    def create_qt_battery_icon(level: int, threshold: int) -> "QIcon":
        """Convert the generated PIL badge into a Qt icon."""
        app = QApplication.instance() or QApplication([])
        from PIL import Image as PILImage
        icon = QIcon()
        for size in (16, 22, 24, 32, 48, 64):
            image = create_battery_icon(level, threshold).resize((size, size), PILImage.Resampling.LANCZOS)
            buffer = BytesIO()
            image.save(buffer, format="PNG")
            qimage = QImage.fromData(buffer.getvalue(), "PNG")
            icon.addPixmap(QPixmap.fromImage(qimage))
        return icon


if IS_WINDOWS:
    def create_windows_battery_icon(level: int, threshold: int):
        """Generate a Windows tray icon matching the Linux thin-circle style.

        Rendered at 64×64 (the size pystray uses on Windows) so the 3px outline
        maps to roughly 1px at the 20-32px notification-area icon size.
        """
        size = 64
        return _render_battery_icon(
            level,
            threshold,
            size=size,
            ring_box=[1, 1, size - 2, size - 2],
            ring_width=3,
            font_names=["arial.ttf"],
            font_size_lt100=45,
            font_size_100=36,
            stroke_width=1,
            stroke_fill=(0, 0, 0, 200),
        )


# ── Settings window ────────────────────────────────────────────────────────

class SettingsWindow:
    """Tkinter settings window for MouseWatch."""

    _instance = None

    def __init__(self, tray_app: "TrayApp"):
        if SettingsWindow._instance is not None:
            try:
                SettingsWindow._instance._root.lift()
                SettingsWindow._instance._root.focus_force()
                return
            except Exception:
                SettingsWindow._instance = None

        SettingsWindow._instance = self
        self._tray_app = tray_app

        import tkinter as tk
        from tkinter import ttk

        self._root = tk.Tk()
        self._root.title("MouseWatch Settings")
        self._root.resizable(False, False)
        self._root.protocol("WM_DELETE_WINDOW", self._on_close)

        frame = ttk.Frame(self._root, padding=16)
        frame.grid(sticky="nsew")

        row = 0

        ttk.Label(frame, text="Battery threshold (%):").grid(
            row=row, column=0, sticky="w", pady=4)
        self._threshold_var = tk.IntVar(value=tray_app.threshold)
        ttk.Spinbox(frame, from_=1, to=100, textvariable=self._threshold_var,
                     width=8).grid(row=row, column=1, sticky="w", pady=4)

        row += 1
        ttk.Label(frame, text="Reminder interval (s):").grid(
            row=row, column=0, sticky="w", pady=4)
        self._reminder_var = tk.IntVar(value=tray_app.reminder_interval)
        ttk.Spinbox(frame, from_=60, to=3600, textvariable=self._reminder_var,
                     width=8).grid(row=row, column=1, sticky="w", pady=4)

        row += 1
        ttk.Label(frame, text="Poll interval (s):").grid(
            row=row, column=0, sticky="w", pady=4)
        self._poll_var = tk.IntVar(value=tray_app.interval)
        ttk.Spinbox(frame, from_=30, to=3600, textvariable=self._poll_var,
                     width=8).grid(row=row, column=1, sticky="w", pady=4)

        row += 1
        self._sound_var = tk.BooleanVar(value=tray_app.notification_sound)
        ttk.Checkbutton(frame, text="Notification sound",
                         variable=self._sound_var).grid(
            row=row, column=0, columnspan=2, sticky="w", pady=4)

        row += 1
        self._devnotify_var = tk.BooleanVar(value=tray_app.device_notifications)
        ttk.Checkbutton(frame, text="Device connect/disconnect notifications",
                         variable=self._devnotify_var).grid(
            row=row, column=0, columnspan=2, sticky="w", pady=4)

        row += 1
        startup_label = Common.startup_label()
        self._startup_var = tk.BooleanVar(value=_startup_shortcut_exists())
        ttk.Checkbutton(frame, text=startup_label,
                         variable=self._startup_var).grid(
            row=row, column=0, columnspan=2, sticky="w", pady=4)

        row += 1
        btn_frame = ttk.Frame(frame)
        btn_frame.grid(row=row, column=0, columnspan=2, pady=(12, 0))
        ttk.Button(btn_frame, text="Save", command=self._on_save).pack(
            side="left", padx=4)
        ttk.Button(btn_frame, text="Cancel", command=self._on_close).pack(
            side="left", padx=4)

        self._root.mainloop()

    def _on_save(self):
        settings = {
            "threshold": self._threshold_var.get(),
            "reminder_interval": self._reminder_var.get(),
            "poll_interval": self._poll_var.get(),
            "notification_sound": self._sound_var.get(),
            "device_notifications": self._devnotify_var.get(),
            "start_with_windows": self._startup_var.get(),
        }
        Common.persist_and_apply_settings(self._tray_app, settings)
        self._on_close()

    def _on_close(self):
        SettingsWindow._instance = None
        self._root.destroy()


class DebugWindow:
    """Tkinter debug window showing raw HID data."""

    _instance = None

    def __init__(self, tray_app: "TrayApp"):
        if DebugWindow._instance is not None:
            try:
                DebugWindow._instance._root.lift()
                DebugWindow._instance._root.focus_force()
                DebugWindow._instance._refresh()
                return
            except Exception:
                DebugWindow._instance = None

        DebugWindow._instance = self
        self._tray_app = tray_app

        import tkinter as tk
        from tkinter import ttk

        self._root = tk.Tk()
        self._root.title("MouseWatch Debug")
        self._root.resizable(False, False)
        self._root.protocol("WM_DELETE_WINDOW", self._on_close)

        frame = ttk.Frame(self._root, padding=16)
        frame.grid(sticky="nsew")

        self._text = tk.Text(frame, width=70, height=20, font=("Consolas", 10),
                              state="disabled")
        self._text.grid(row=0, column=0, columnspan=2)

        ttk.Button(frame, text="Refresh", command=self._refresh).grid(
            row=1, column=0, pady=(8, 0), sticky="e", padx=4)
        ttk.Button(frame, text="Close", command=self._on_close).grid(
            row=1, column=1, pady=(8, 0), sticky="w", padx=4)

        self._refresh()
        self._root.mainloop()

    def _refresh(self):
        app = self._tray_app
        snapshot = app.refresh_debug_snapshot()
        lines = Common.build_debug_lines(app, snapshot, section_title="── Last E2 Input Report ──")

        import tkinter as tk
        self._text.config(state="normal")
        self._text.delete("1.0", tk.END)
        self._text.insert("1.0", "\n".join(lines))
        self._text.config(state="disabled")

    def _on_close(self):
        DebugWindow._instance = None
        self._root.destroy()


if not IS_WINDOWS:
  class QtSettingsDialog(QDialog):
    """Qt settings dialog for MouseWatch."""

    def __init__(self, tray_app: "QtTrayApp"):
        super().__init__()
        self._tray_app = tray_app
        self.setWindowTitle("MouseWatch Settings")
        self.setModal(False)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self._threshold_spin = QSpinBox()
        self._threshold_spin.setRange(1, 100)
        self._threshold_spin.setValue(tray_app.threshold)
        form.addRow("Battery threshold (%):", self._threshold_spin)

        self._reminder_spin = QSpinBox()
        self._reminder_spin.setRange(60, 3600)
        self._reminder_spin.setValue(tray_app.reminder_interval)
        form.addRow("Reminder interval (s):", self._reminder_spin)

        self._poll_spin = QSpinBox()
        self._poll_spin.setRange(30, 3600)
        self._poll_spin.setValue(tray_app.interval)
        form.addRow("Poll interval (s):", self._poll_spin)

        self._sound_check = QCheckBox("Notification sound")
        self._sound_check.setChecked(tray_app.notification_sound)
        form.addRow(self._sound_check)

        self._device_check = QCheckBox("Device connect/disconnect notifications")
        self._device_check.setChecked(tray_app.device_notifications)
        form.addRow(self._device_check)

        self._startup_check = QCheckBox(Common.startup_label())
        self._startup_check.setChecked(_startup_shortcut_exists())
        form.addRow(self._startup_check)

        layout.addLayout(form)

        button_row = QHBoxLayout()
        self._save_button = QPushButton("Save")
        self._cancel_button = QPushButton("Cancel")
        self._save_button.clicked.connect(self._on_save)
        self._cancel_button.clicked.connect(self.close)
        button_row.addStretch(1)
        button_row.addWidget(self._save_button)
        button_row.addWidget(self._cancel_button)
        layout.addLayout(button_row)

    def _on_save(self):
        settings = {
            "threshold": self._threshold_spin.value(),
            "reminder_interval": self._reminder_spin.value(),
            "poll_interval": self._poll_spin.value(),
            "notification_sound": self._sound_check.isChecked(),
            "device_notifications": self._device_check.isChecked(),
            "start_with_windows": self._startup_check.isChecked(),
        }
        Common.persist_and_apply_settings(self._tray_app, settings)
        self.close()

  class QtDebugDialog(QDialog):
    """Qt debug dialog showing raw HID data."""

    def __init__(self, tray_app: "QtTrayApp"):
        super().__init__()
        self._tray_app = tray_app
        self.setWindowTitle("MouseWatch Debug")
        self.setModal(False)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)

        layout = QVBoxLayout(self)
        self._text = QPlainTextEdit()
        self._text.setReadOnly(True)
        self._text.setMinimumSize(640, 360)
        layout.addWidget(self._text)

        button_row = QHBoxLayout()
        self._refresh_button = QPushButton("Refresh")
        self._close_button = QPushButton("Close")
        self._refresh_button.clicked.connect(self.refresh)
        self._close_button.clicked.connect(self.close)
        button_row.addStretch(1)
        button_row.addWidget(self._refresh_button)
        button_row.addWidget(self._close_button)
        layout.addLayout(button_row)

        self.refresh()

    def refresh(self):
        app = self._tray_app
        snapshot = app.refresh_debug_snapshot()
        lines = Common.build_debug_lines(app, snapshot)

        self._text.setPlainText("\n".join(lines))

  class QtTrayApp(QObject, Common):
      """Qt system tray application for MouseWatch."""

      status_changed = Signal(int, bool, str)
      notification_requested = Signal(str, str)

      def __init__(self, model: str, hid_path: bytes, initial_resp: dict,
                   settings: dict, is_autostart: bool = False):
          super().__init__()
          self.model = model
          self.hid_path = hid_path
          self.is_autostart = is_autostart
          self.threshold = settings["threshold"]
          self.interval = settings["poll_interval"]
          self.reminder_interval = settings["reminder_interval"]
          self.notification_sound = settings["notification_sound"]
          self.device_notifications = settings["device_notifications"]
          self.notified_at = None
          self._last_notify_time = 0
          self._notified_full = False
          self.level, self.charging = Common.status_from_response(initial_resp)
          self.status_text = self._status_text()
          self._stop_event = threading.Event()
          self._poll_interrupt = threading.Event()
          self._last_e2_raw = None
          self._last_e2_decoded = None
          self._last_e2_time = None
          self._last_debug_refresh_time = None
          self._settings_dialog = None
          self._debug_dialog = None

          _existing = QApplication.instance()
          if isinstance(_existing, QApplication):
              _app = _existing
          else:
              _app = QApplication(sys.argv)
          self._app: QApplication = _app  # type: ignore[assignment]
          self._app.setApplicationName("MouseWatch")
          self._app.setQuitOnLastWindowClosed(False)

          self.tray = QSystemTrayIcon()
          self.tray.setVisible(False)
          self.tray.activated.connect(self._on_activated)

          self._menu = QMenu()
          self._status_action = QAction("Status", self)
          self._settings_action = QAction("Settings", self)
          self._debug_action = QAction("Debug", self)
          self._quit_action = QAction("Quit", self)
          self._status_action.triggered.connect(self._on_status)
          self._settings_action.triggered.connect(self._on_settings)
          self._debug_action.triggered.connect(self._on_debug)
          self._quit_action.triggered.connect(self._on_quit)
          self._menu.addAction(self._status_action)
          self._menu.addAction(self._settings_action)
          self._menu.addAction(self._debug_action)
          self._menu.addSeparator()
          self._menu.addAction(self._quit_action)
          self.tray.setContextMenu(self._menu)

          self.status_changed.connect(self._apply_status)
          self.notification_requested.connect(self._show_notification)
          self._apply_status(self.level, self.charging, self.status_text)

      def _apply_status(self, level: int, charging: bool, status_text: str):
          self.level = level
          self.charging = charging
          self.status_text = status_text
          self.tray.setIcon(create_qt_battery_icon(self.level, self.threshold))
          self.tray.setToolTip(self.status_text)
          self.tray.setVisible(True)

      def _update_ui_status(self):
          self.status_changed.emit(self.level, self.charging, self.status_text)

      def _show_notification(self, title: str, message: str):
          # Run notify-send in a daemon thread so it never blocks the Qt event
          # loop and never causes QSystemTrayIcon to temporarily swap the icon.
          def _send():
              try:
                  subprocess.run(["notify-send", title, message], check=False)
              except FileNotFoundError:
                  pass
          threading.Thread(target=_send, daemon=True).start()

      def _notify(self, title: str, message: str):
          self.notification_requested.emit(title, message)

      def _on_activated(self, reason):
          if reason == QSystemTrayIcon.ActivationReason.Trigger:
              self._on_status()

      def _on_status(self, checked: bool = False):
          msg = self._refresh_status()
          self._notify("MouseWatch", msg)

      def _on_settings(self, checked: bool = False):
          dialog = QtSettingsDialog(self)
          dialog.show()
          dialog.raise_()
          dialog.activateWindow()
          self._settings_dialog = dialog

      def _on_debug(self, checked: bool = False):
          dialog = QtDebugDialog(self)
          dialog.show()
          dialog.raise_()
          dialog.activateWindow()
          self._debug_dialog = dialog

      def _on_quit(self, checked: bool = False):
          self._stop_event.set()
          self._poll_interrupt.set()
          self.tray.hide()
          self._app.quit()

      def run(self):
          if self.is_autostart:
              # During autostart, wait up to 60 seconds for system tray to become available
              for attempt in range(60):
                  if QSystemTrayIcon.isSystemTrayAvailable():
                      break
                  time.sleep(1)
              else:
                  print("System tray did not become available during autostart; exiting.")
                  sys.exit(1)
          elif not QSystemTrayIcon.isSystemTrayAvailable():
              print("System tray is not available in this desktop session.")
              sys.exit(1)

          self.tray.show()

          poll_thread = threading.Thread(target=self._poll_loop, daemon=True)
          poll_thread.start()

          input_thread = threading.Thread(target=self._input_listener, daemon=True)
          input_thread.start()

          watcher_thread = threading.Thread(target=self._device_watcher, daemon=True)
          watcher_thread.start()

          self._app.exec()


# ── System tray ────────────────────────────────────────────────────────────

class TrayApp(Common):
    """System tray application for MouseWatch."""

    def __init__(self, model: str, hid_path: bytes, initial_resp: dict,
                 settings: dict):
        self.model = model
        self.hid_path = hid_path
        self.threshold = settings["threshold"]
        self.interval = settings["poll_interval"]
        self.reminder_interval = settings["reminder_interval"]
        self.notification_sound = settings["notification_sound"]
        self.device_notifications = settings["device_notifications"]
        self.notified_at = None
        self._last_notify_time = 0
        self._notified_full = False
        self.level, self.charging = Common.status_from_response(initial_resp)
        self.status_text = self._status_text()
        self._stop_event = threading.Event()
        self._poll_interrupt = threading.Event()
        self.icon = None
        self._last_e2_raw = None
        self._last_e2_decoded = None
        self._last_e2_time = None
        self._menu_supported = True
        self._fallback_ui_started = False
        self._last_debug_refresh_time = None

    def _create_menu(self):
        import pystray
        if not self._menu_supported:
            return None
        return pystray.Menu(
            pystray.MenuItem("Status", self._on_status, default=True),
            pystray.MenuItem("Settings", self._on_settings),
            pystray.MenuItem("Debug", self._on_debug),
            pystray.MenuItem("Quit", self._on_quit),
        )

    def _update_ui_status(self):
        if self.icon:
            self.icon.icon = create_windows_battery_icon(self.level, self.threshold)
            self.icon.title = self.status_text

    def _notify(self, title: str, message: str):
        safe_notify(title, message, sound=self.notification_sound)

    def _on_status(self, icon, item):
        msg = self._refresh_status()
        self._notify("MouseWatch", msg)

    def _on_settings(self, icon, item):
        threading.Thread(target=SettingsWindow, args=(self,),
                         daemon=True).start()

    def _on_debug(self, icon, item):
        threading.Thread(target=DebugWindow, args=(self,),
                         daemon=True).start()

    def _on_quit(self, icon, item):
        self._stop_event.set()
        self._poll_interrupt.set()
        icon.stop()

    def _on_quit_direct(self):
        self._stop_event.set()
        self._poll_interrupt.set()
        if self.icon:
            self.icon.stop()

    def _run_fallback_control_window(self):
        """Show controls when tray backend cannot render context menus."""
        if self._fallback_ui_started:
            return
        self._fallback_ui_started = True

        import tkinter as tk
        from tkinter import ttk

        root = tk.Tk()
        root.title("MouseWatch")
        root.resizable(False, False)

        frame = ttk.Frame(root, padding=12)
        frame.grid(sticky="nsew")

        status_var = tk.StringVar(value=self.status_text)
        ttk.Label(frame, textvariable=status_var).grid(row=0, column=0, columnspan=2,
                                                        sticky="w", pady=(0, 8))

        def refresh_click():
            msg = self._refresh_status()
            status_var.set(self.status_text)
            self._notify("MouseWatch", msg)

        ttk.Button(frame, text="Refresh", command=refresh_click).grid(
            row=1, column=0, sticky="ew", padx=(0, 4), pady=4)
        ttk.Button(frame, text="Settings", command=lambda: self._on_settings(None, None)).grid(
            row=1, column=1, sticky="ew", padx=(4, 0), pady=4)
        ttk.Button(frame, text="Debug", command=lambda: self._on_debug(None, None)).grid(
            row=2, column=0, sticky="ew", padx=(0, 4), pady=4)
        ttk.Button(frame, text="Quit", command=self._on_quit_direct).grid(
            row=2, column=1, sticky="ew", padx=(4, 0), pady=4)

        def ticker():
            status_var.set(self.status_text)
            if not self._stop_event.is_set():
                root.after(1000, ticker)
            else:
                root.destroy()

        root.after(1000, ticker)
        root.mainloop()


    def run(self):
        import pystray

        self._menu_supported = bool(getattr(pystray.Icon, "HAS_MENU", True))

        image = create_windows_battery_icon(self.level, self.threshold)
        self.icon = pystray.Icon(
            "MouseWatch",
            image,
            title=self.status_text,
            menu=self._create_menu(),
        )

        if IS_LINUX and not self._menu_supported:
            print("Tray backend has no menu support on this Linux session.")
            print("Opening MouseWatch control window for Settings/Debug/Quit.")
            threading.Thread(target=self._run_fallback_control_window,
                             daemon=True).start()

        poll_thread = threading.Thread(target=self._poll_loop, daemon=True)
        poll_thread.start()

        input_thread = threading.Thread(target=self._input_listener, daemon=True)
        input_thread.start()

        watcher_thread = threading.Thread(target=self._device_watcher, daemon=True)
        watcher_thread.start()

        self.icon.run()


# ── CLI mode (--nogui) ────────────────────────────────────────────────────

def run_cli(model, hid_path, args):
    """Original CLI poll loop."""
    print(f"\nMonitoring MCHOSE {model}")
    print(f"  Threshold:  {args.threshold}%")
    print(f"  Interval:   {args.interval}s")
    if args.once:
        print(f"  Mode:       single query")
    print()

    notified_at = None

    while True:
        resp = query_battery(hid_path)
        if resp is None:
            print(f"[{time.strftime('%H:%M:%S')}] Failed to read battery "
                  "(mouse asleep or disconnected)")
        else:
            level, charging = Common.status_from_response(resp)
            status = "Charging" if charging else "Wireless"
            print(f"[{time.strftime('%H:%M:%S')}] Battery: {level}%  ({status})")

            if level <= args.threshold and not charging and notified_at != level:
                notified_at = level
                msg = f"MCHOSE {model} battery is at {level}%"
                print(f"  >> LOW BATTERY ALERT: {msg}")
                safe_notify("MouseWatch - Low Battery", msg)
            elif level > args.threshold:
                notified_at = None

        if args.once:
            break

        try:
            time.sleep(args.interval)
        except KeyboardInterrupt:
            print("\nStopped.")
            break


# ── Main ──────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="MouseWatch - Battery monitor for MCHOSE wireless mice"
    )
    parser.add_argument(
        "-t", "--threshold",
        type=int,
        default=None,
        help="Battery percentage to trigger alert (default: from config or 20)",
    )
    parser.add_argument(
        "-i", "--interval",
        type=int,
        default=None,
        help="Polling interval in seconds (default: from config or 300)",
    )
    parser.add_argument(
        "-m", "--model",
        type=str,
        default=None,
        help="Mouse model name (skip auto-detection)",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Query battery once and exit (CLI mode)",
    )
    parser.add_argument(
        "--nogui",
        action="store_true",
        help="Run in CLI mode (no system tray)",
    )
    parser.add_argument(
        "--autostart",
        action="store_true",
        help="Running from autostart (GUI waits for tray availability)",
    )
    args = parser.parse_args()
    stdin_is_interactive = bool(getattr(sys.stdin, "isatty", lambda: False)())

    if (IS_LINUX and not args.nogui and not args.autostart
            and not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))):
        print("No desktop session detected; switching to CLI mode (--nogui).")
        args.nogui = True

    # Load persisted settings, then let CLI args override
    settings = load_settings()
    if args.threshold is not None:
        settings["threshold"] = args.threshold
    if args.interval is not None:
        settings["poll_interval"] = args.interval

    if settings["threshold"] < 1 or settings["threshold"] > 100:
        print("Error: threshold must be between 1 and 100")
        sys.exit(1)

    # --once implies --nogui
    if args.once:
        args.nogui = True

    # ── Detect mouse ──
    hid_path = None
    resp = None
    model = args.model

    if model and model not in MOUSE_DB:
        print(f"Unknown model '{model}'. Use one of:")
        for name in sorted(MOUSE_DB.keys()):
            print(f"  {name}")
        sys.exit(1)

    if args.nogui:
        # CLI mode: interactive detection with prompts
        print("MouseWatch - MCHOSE Battery Monitor")
        print("=" * 40)

        if model is None:
            print("\nSearching for MCHOSE mouse...")
            result = autodetect()
            if result:
                model, hid_path, resp = result
                print(f"  Detected: MCHOSE {model}")
                print(f"  Battery:  {resp['battery_level']}%")
                charging = resp["charge_status"] != 0 or resp["connect_mode"] == 0
                print(f"  Status:   {'Charging' if charging else 'Wireless'}")
                if stdin_is_interactive and not args.once:
                    print()
                    confirm = input("Is this correct? [Y/n] ").strip().lower()
                    if confirm and confirm != "y":
                        model = pick_model()
                        hid_path = None
            else:
                print("  No MCHOSE mouse detected automatically.")
                if args.once:
                    print("  Hint: if you see 'HID error: open failed', fix Linux hidraw permissions first.")
                    sys.exit(1)
                if not stdin_is_interactive:
                    print("  Cannot prompt for model selection in a non-interactive session.")
                    print("  Re-run interactively or pass --model to force a specific mouse model.")
                    sys.exit(1)
                model = pick_model()
    else:
        # GUI mode: silent auto-detection
        if model is None:
            result = autodetect()
            if result:
                model, hid_path, resp = result
            else:
                wired = find_wired_mchose()
                if wired:
                    # Start in wired mode — no battery data yet,
                    # input listener will pick up E2 reports.
                    name = wired["name"].replace("MCHOSE ", "")
                    model = name or "Unknown"
                    hid_path = wired["path"]
                    resp = {
                        "battery_level": 0,
                        "charge_status": 1,
                        "connect_mode": 0,
                    }
                else:
                    msg = ("No MCHOSE mouse detected. Make sure it's connected "
                           "via the 2.4GHz dongle.")
                    safe_notify("MouseWatch", msg)
                    sys.exit(1)

    # ── Find HID path if not yet resolved ──
    if hid_path is None:
        devices = find_mchose_devices()
        for dev in devices:
            resp = Common.query_after_throwaway(dev["path"])
            if resp:
                hid_path = dev["path"]
                break
        if hid_path is None:
            msg = (f"Could not find HID device for MCHOSE {model}. "
                   "Make sure the mouse is connected via the 2.4GHz dongle.")
            if args.nogui:
                print(f"\n{msg}")
            else:
                safe_notify("MouseWatch", msg)
            sys.exit(1)

    # Get fresh reading for initial state (needed when HID path was found via manual pick)
    if resp is None:
        resp = Common.query_after_throwaway(hid_path)
        if resp is None:
            resp = Common.query_battery_retry(hid_path)
        if resp is None:
            msg = "Failed to read battery status."
            if args.nogui:
                print(msg)
            else:
                safe_notify("MouseWatch", msg)
            sys.exit(1)

    if args.nogui:
        # CLI mode uses threshold/interval from settings
        args.threshold = settings["threshold"]
        args.interval = settings["poll_interval"]
        run_cli(model, hid_path, args)
    else:
        if IS_WINDOWS:
            app = TrayApp(model, hid_path, resp, settings)
        else:
            app = QtTrayApp(model, hid_path, resp, settings, is_autostart=args.autostart)
        app.run()


if __name__ == "__main__":
    main()
