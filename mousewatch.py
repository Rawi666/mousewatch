"""
MouseWatch - Battery monitor for MCHOSE wireless mice.

Polls battery level via HID and shows status in the system tray.
Low battery triggers a Windows toast notification.

Protocol reverse-engineered from the MCHOSE WebHID configurator.
"""

import argparse
import json
import os
import struct
import sys
import threading
import time

import hid

# ── Settings persistence ──────────────────────────────────────────────────

DEFAULTS = {
    "threshold": 20,
    "reminder_interval": 300,
    "poll_interval": 300,
    "notification_sound": True,
    "start_with_windows": False,
}


def _config_dir() -> str:
    return os.path.join(os.environ.get("LOCALAPPDATA", "."), "MouseWatch")


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
    return os.path.join(
        os.environ.get("APPDATA", "."),
        "Microsoft", "Windows", "Start Menu", "Programs", "Startup",
        "MouseWatch.lnk",
    )


def _startup_shortcut_exists() -> bool:
    return os.path.exists(_startup_shortcut_path())


def _set_startup(enabled: bool):
    """Create or remove the startup shortcut."""
    lnk_path = _startup_shortcut_path()
    if enabled:
        if getattr(sys, "frozen", False):
            target = sys.executable
            arguments = ""
        else:
            target = sys.executable  # python.exe
            arguments = f'"{os.path.abspath(sys.argv[0])}"'
        # Create .lnk via PowerShell
        import subprocess
        ps_script = (
            f"$ws = New-Object -ComObject WScript.Shell; "
            f"$sc = $ws.CreateShortcut('{lnk_path}'); "
            f"$sc.TargetPath = '{target}'; "
            f"$sc.Arguments = '{arguments}'; "
            f"$sc.Save()"
        )
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_script],
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    else:
        if os.path.exists(lnk_path):
            os.remove(lnk_path)

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

# ── HID protocol constants ─────────────────────────────────────────────────
REPORT_ID = 0x11
CMD_GET_STATUS = 0x06


def xor_encode(data: list[int]) -> list[int]:
    return [b ^ 0xFF for b in data]


def xor_decode(data: bytes) -> bytes:
    return bytes(b ^ 0xFF for b in data)


# ── Device discovery ───────────────────────────────────────────────────────

def find_mchose_devices() -> list[dict]:
    """Enumerate HID devices and return MCHOSE mouse interfaces on vendor usage pages."""
    results = []
    seen_paths = set()
    for vid in ALL_VIDS:
        for dev in hid.enumerate(vid):
            if dev["usage_page"] in USAGE_PAGES and dev["path"] not in seen_paths:
                seen_paths.add(dev["path"])
                results.append(dev)
    results.sort(key=lambda d: (d["usage_page"] != 0xFF01, d["usage_page"]))
    return results


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
        print(f"  [!] HID error: {e}")
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
        query_battery(dev["path"])
        time.sleep(0.1)
        resp = query_battery(dev["path"])
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


# ── Windows notification ───────────────────────────────────────────────────

def notify_windows(title: str, message: str, sound: bool = True):
    """Show a Windows toast notification."""
    from winotify import Notification, audio
    toast = Notification(
        app_id="MouseWatch",
        title=title,
        msg=message,
        duration="long",
    )
    toast.set_audio(audio.Default if sound else audio.Silent, loop=False)
    toast.show()


# ── Icon generation ────────────────────────────────────────────────────────

def _battery_color(level: int, charging: bool) -> str:
    """Return hex color based on battery level and charging state."""
    if charging:
        return "#4FC3F7"  # light blue
    if level > 50:
        return "#4CAF50"  # green
    if level > 20:
        return "#FFC107"  # yellow/amber
    return "#F44336"  # red


def create_battery_icon(level: int, charging: bool):
    """Generate a 64x64 PIL Image showing battery percentage."""
    from PIL import Image, ImageDraw, ImageFont

    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    color = _battery_color(level, charging)

    # Draw filled circle background
    draw.ellipse([2, 2, size - 3, size - 3], fill=color)

    # Draw percentage text
    text = str(level)
    try:
        font = ImageFont.truetype("arial.ttf", 26 if level < 100 else 20)
    except OSError:
        font = ImageFont.load_default()

    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    tx = (size - tw) // 2 - bbox[0]
    ty = (size - th) // 2 - bbox[1]
    draw.text((tx, ty), text, fill="white", font=font)

    # Charging indicator: small lightning bolt in bottom-right
    if charging:
        bolt = [(46, 38), (50, 38), (48, 44), (52, 44), (45, 56), (48, 47), (44, 47)]
        draw.polygon(bolt, fill="white")

    return img


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
        self._startup_var = tk.BooleanVar(value=_startup_shortcut_exists())
        ttk.Checkbutton(frame, text="Start with Windows",
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
            "start_with_windows": self._startup_var.get(),
        }
        save_settings(settings)

        app = self._tray_app
        app.threshold = settings["threshold"]
        app.reminder_interval = settings["reminder_interval"]
        app.notification_sound = settings["notification_sound"]

        # If poll interval changed, interrupt current wait so it takes effect
        if app.interval != settings["poll_interval"]:
            app.interval = settings["poll_interval"]
            app._poll_interrupt.set()

        _set_startup(settings["start_with_windows"])
        self._on_close()

    def _on_close(self):
        SettingsWindow._instance = None
        self._root.destroy()


# ── System tray ────────────────────────────────────────────────────────────

class TrayApp:
    """System tray application for MouseWatch."""

    def __init__(self, model: str, hid_path: bytes, initial_resp: dict,
                 settings: dict):
        self.model = model
        self.hid_path = hid_path
        self.threshold = settings["threshold"]
        self.interval = settings["poll_interval"]
        self.reminder_interval = settings["reminder_interval"]
        self.notification_sound = settings["notification_sound"]
        self.notified_at = None
        self._last_notify_time = 0
        self.level = initial_resp["battery_level"]
        self.charging = (initial_resp["charge_status"] != 0
                         or initial_resp["connect_mode"] == 0)
        self.status_text = self._status_text()
        self._stop_event = threading.Event()
        self._poll_interrupt = threading.Event()
        self.icon = None

    def _status_text(self) -> str:
        status = "Charging" if self.charging else "Wireless"
        return f"MCHOSE {self.model} — {self.level}% ({status})"

    def _create_menu(self):
        import pystray
        return pystray.Menu(
            pystray.MenuItem("Status", self._on_status, default=True),
            pystray.MenuItem("Settings", self._on_settings),
            pystray.MenuItem("Quit", self._on_quit),
        )

    def _on_status(self, icon, item):
        try:
            notify_windows("MouseWatch", self.status_text,
                           sound=self.notification_sound)
        except Exception:
            pass

    def _on_settings(self, icon, item):
        threading.Thread(target=SettingsWindow, args=(self,),
                         daemon=True).start()

    def _on_quit(self, icon, item):
        self._stop_event.set()
        self._poll_interrupt.set()
        icon.stop()

    def _poll_loop(self):
        """Background thread that polls battery and updates the tray icon."""
        while True:
            self._poll_interrupt.wait(self.interval)
            if self._stop_event.is_set():
                break
            self._poll_interrupt.clear()

            resp = query_battery(self.hid_path)
            for _ in range(5):
                if resp is not None:
                    break
                time.sleep(2)
                resp = query_battery(self.hid_path)
            if resp is None:
                continue

            self.level = resp["battery_level"]
            self.charging = (resp["charge_status"] != 0
                             or resp["connect_mode"] == 0)
            self.status_text = self._status_text()

            # Update icon and tooltip
            self.icon.icon = create_battery_icon(self.level, self.charging)
            self.icon.title = self.status_text

            # Low battery notification with reminder interval
            now = time.time()
            if (self.level <= self.threshold and not self.charging
                    and (now - self._last_notify_time) >= self.reminder_interval):
                self._last_notify_time = now
                try:
                    notify_windows(
                        "MouseWatch - Low Battery",
                        f"MCHOSE {self.model} battery is at {self.level}%",
                        sound=self.notification_sound,
                    )
                except Exception:
                    pass
            elif self.level > self.threshold:
                self._last_notify_time = 0

    def run(self):
        import pystray

        image = create_battery_icon(self.level, self.charging)
        self.icon = pystray.Icon(
            "MouseWatch",
            image,
            title=self.status_text,
            menu=self._create_menu(),
        )

        poll_thread = threading.Thread(target=self._poll_loop, daemon=True)
        poll_thread.start()

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
            level = resp["battery_level"]
            charging = resp["charge_status"] != 0 or resp["connect_mode"] == 0
            status = "Charging" if charging else "Wireless"
            print(f"[{time.strftime('%H:%M:%S')}] Battery: {level}%  ({status})")

            if level <= args.threshold and not charging and notified_at != level:
                notified_at = level
                msg = f"MCHOSE {model} battery is at {level}%"
                print(f"  >> LOW BATTERY ALERT: {msg}")
                try:
                    notify_windows("MouseWatch - Low Battery", msg)
                except Exception as e:
                    print(f"  [!] Notification error: {e}")
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
    args = parser.parse_args()

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
                print()
                confirm = input("Is this correct? [Y/n] ").strip().lower()
                if confirm and confirm != "y":
                    model = pick_model()
                    hid_path = None
            else:
                print("  No MCHOSE mouse detected automatically.")
                model = pick_model()
    else:
        # GUI mode: silent auto-detection
        if model is None:
            result = autodetect()
            if result:
                model, hid_path, resp = result
            else:
                try:
                    notify_windows(
                        "MouseWatch",
                        "No MCHOSE mouse detected. Make sure it's connected "
                        "via the 2.4GHz dongle.",
                    )
                except Exception:
                    pass
                sys.exit(1)

    # ── Find HID path if not yet resolved ──
    if hid_path is None:
        devices = find_mchose_devices()
        for dev in devices:
            query_battery(dev["path"])
            time.sleep(0.1)
            resp = query_battery(dev["path"])
            if resp:
                hid_path = dev["path"]
                break
        if hid_path is None:
            msg = (f"Could not find HID device for MCHOSE {model}. "
                   "Make sure the mouse is connected via the 2.4GHz dongle.")
            if args.nogui:
                print(f"\n{msg}")
            else:
                try:
                    notify_windows("MouseWatch", msg)
                except Exception:
                    pass
            sys.exit(1)

    # Get fresh reading for initial state (needed when HID path was found via manual pick)
    if resp is None:
        query_battery(hid_path)
        time.sleep(0.1)
        resp = query_battery(hid_path)
        if resp is None:
            msg = "Failed to read battery status."
            if args.nogui:
                print(msg)
            else:
                try:
                    notify_windows("MouseWatch", msg)
                except Exception:
                    pass
            sys.exit(1)

    if args.nogui:
        # CLI mode uses threshold/interval from settings
        args.threshold = settings["threshold"]
        args.interval = settings["poll_interval"]
        run_cli(model, hid_path, args)
    else:
        app = TrayApp(model, hid_path, resp, settings)
        app.run()


if __name__ == "__main__":
    main()
