import subprocess
import threading
import time
import traceback
from contextlib import nullcontext
from typing import Any

try:
    from .mw_platform import IS_LINUX, IS_WINDOWS, hid
    from .settings_store import save_settings, set_startup
except ImportError:
    from mw_platform import IS_LINUX, IS_WINDOWS, hid
    from settings_store import save_settings, set_startup


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
        try:
            subprocess.run(["notify-send", title, message], check=False)
        except FileNotFoundError:
            print(f"{title}: {message}")
        return

    print(f"{title}: {message}")


def safe_notify(title: str, message: str, sound: bool = True):
    try:
        notify_windows(title, message, sound=sound)
        return True
    except Exception as exc:
        print(f"Notification error: {exc}")
        traceback.print_exc()
        return False


class Common:
    """Shared cross-platform app logic used by both tray implementations."""

    model: str
    hid_path: bytes | None
    protocol: Any
    available_protocols: list[Any]
    threshold: int
    interval: int
    reminder_interval: int
    notification_sound: bool
    device_notifications: bool
    level: int
    charging: bool
    device_online: bool
    status_text: str
    _last_notify_time: float
    _notified_full: bool
    _stop_event: threading.Event
    _poll_interrupt: threading.Event
    _last_input_raw: list[int] | None
    _last_input_decoded: list[int] | None
    _last_input_time: str | None
    _last_debug_refresh_time: str | None
    _state_lock: threading.RLock

    def _notify(self, title: str, message: str):
        raise NotImplementedError

    def _update_ui_status(self):
        raise NotImplementedError

    @staticmethod
    def startup_label() -> str:
        return "Start with Windows" if IS_WINDOWS else "Start on login"

    @staticmethod
    def status_from_response(protocol, resp: dict) -> tuple[int, bool]:
        return protocol.status_from_response(resp)

    @staticmethod
    def format_status_text(protocol, model: str, level: int, charging: bool) -> str:
        return protocol.format_status_text(model, level, charging)

    @staticmethod
    def init_runtime_state(
        app,
        protocol,
        model: str,
        hid_path: bytes | None,
        initial_resp: dict | None,
        settings: dict,
        available_protocols: list[Any] | None = None,
    ):
        """Initialize shared runtime state used by both tray implementations."""
        app.protocol = protocol
        app.available_protocols = available_protocols or [protocol]
        app.model = model
        app.hid_path = hid_path
        app.threshold = settings["threshold"]
        app.interval = settings["poll_interval"]
        app.reminder_interval = settings["reminder_interval"]
        app.notification_sound = settings["notification_sound"]
        app.device_notifications = settings["device_notifications"]
        app.notified_at = None
        app._last_notify_time = 0
        app._notified_full = False
        if initial_resp is None:
            app.level = 0
            app.charging = False
            app.device_online = False
        else:
            app.level, app.charging = Common.status_from_response(protocol, initial_resp)
            app.device_online = bool(initial_resp.get("device_online", True))
        app._stop_event = threading.Event()
        app._poll_interrupt = threading.Event()
        app._last_input_raw = None
        app._last_input_decoded = None
        app._last_input_time = None
        app._last_debug_refresh_time = None
        app._state_lock = threading.RLock()
        app.status_text = app._status_text()

    @staticmethod
    def query_battery_retry(protocol, hid_path: bytes, retries: int = 5, delay: float = 2.0) -> dict | None:
        resp = protocol.query_battery(hid_path)
        for _ in range(retries):
            if resp is not None:
                break
            time.sleep(delay)
            resp = protocol.query_battery(hid_path)
        return resp

    @staticmethod
    def query_after_throwaway(protocol, hid_path: bytes, settle_delay: float = 0.1) -> dict | None:
        protocol.query_battery(hid_path)
        time.sleep(settle_delay)
        return protocol.query_battery(hid_path)

    @staticmethod
    def apply_settings_to_app(app, settings: dict):
        with app._state_lock:
            app.threshold = settings["threshold"]
            app.reminder_interval = settings["reminder_interval"]
            app.notification_sound = settings["notification_sound"]
            app.device_notifications = settings["device_notifications"]
            poll_interval_changed = app.interval != settings["poll_interval"]
            app.interval = settings["poll_interval"]
        if poll_interval_changed:
            app._poll_interrupt.set()

    @staticmethod
    def persist_and_apply_settings(app, settings: dict):
        save_settings(settings)
        Common.apply_settings_to_app(app, settings)
        set_startup(settings["start_with_windows"])

    @staticmethod
    def build_debug_lines(app, snapshot: dict | None, section_title: str = "Last E2 Input Report") -> list[str]:
        lock = getattr(app, "_state_lock", None)
        guard = lock if lock is not None else nullcontext()
        with guard:
            protocol = app.protocol
            model_name = protocol.format_model_name(app.model)
            level = app.level
            charging = app.charging
            last_refresh = app._last_debug_refresh_time
            last_input_time = app._last_input_time
            last_input_raw = list(app._last_input_raw) if app._last_input_raw is not None else None
            last_input_decoded = list(app._last_input_decoded) if app._last_input_decoded is not None else None

        lines = []
        lines.append(f"Model:   {model_name}")
        lines.append(f"Battery: {level}%")
        lines.append(f"Status:  {'Charging' if charging else 'Wireless'}")
        if last_refresh:
            lines.append(f"Refreshed: {last_refresh}")
        lines.append("")
        lines.append(section_title)

        if last_input_time:
            lines.append(f"Time:    {last_input_time}")
            if last_input_raw is not None:
                lines.append(f"Raw:     {' '.join(f'{b:02X}' for b in last_input_raw)}")
            if last_input_decoded is not None:
                lines.append(f"Decoded: {' '.join(f'{b:02X}' for b in last_input_decoded)}")
                lines.append("")
                protocol.append_debug_input_details(lines, last_input_decoded)
        else:
            lines.append("No input reports received yet.")

        lines.append("")
        if snapshot is None:
            lines.append("Manual refresh: no response")
        else:
            lines.append(f"Manual refresh: battery {snapshot['battery_level']}%")

        return lines

    def _status_text(self) -> str:
        if not getattr(self, "device_online", True):
            return "MouseWatch - Waiting for device"
        return Common.format_status_text(self.protocol, self.model, self.level, self.charging)

    def _set_disconnected_state(self):
        with self._state_lock:
            self.device_online = False
            self.status_text = self._status_text()
        self._update_ui_status()

    def _ordered_device_paths(self, devices: list[dict]) -> list[bytes]:
        """Keep adapter order and de-duplicate paths for deterministic failover."""
        paths: list[bytes] = []
        seen: set[bytes] = set()
        for dev in devices:
            path = dev.get("path")
            if path and path not in seen:
                seen.add(path)
                paths.append(path)
        return paths

    def _pick_first_available_path(self, devices: list[dict]) -> bytes | None:
        paths = self._ordered_device_paths(devices)
        if not paths:
            return None
        return paths[0]

    def _recover_path_and_query(self, retries: int = 5, delay: float = 2.0) -> dict | None:
        """Try current path first, then scan candidate interfaces and switch on success."""
        with self._state_lock:
            current_protocol = self.protocol
            current_path = self.hid_path

        if current_path is not None:
            resp = Common.query_battery_retry(current_protocol, current_path, retries=retries, delay=delay)
            if resp is not None:
                return resp

        devices = current_protocol.discover_devices()
        for path in self._ordered_device_paths(devices):
            if path == current_path:
                continue

            candidate = Common.query_after_throwaway(current_protocol, path, settle_delay=0.05)
            if candidate is None:
                continue

            with self._state_lock:
                self.hid_path = path
            return candidate

        # If current protocol has no viable responder, try alternate protocols.
        for alt_protocol in getattr(self, "available_protocols", []):
            if alt_protocol is current_protocol:
                continue

            detected = alt_protocol.autodetect(Common)
            if detected is None:
                continue

            model, hid_path, resp = detected
            with self._state_lock:
                self.protocol = alt_protocol
                self.model = model
                self.hid_path = hid_path
                self._last_input_raw = None
                self._last_input_decoded = None
                self._last_input_time = None
            return resp

        return None

    def apply_settings(self, settings: dict):
        Common.apply_settings_to_app(self, settings)

    def _refresh_status(self) -> str:
        # Manual refresh should feel responsive; polling still uses longer retries.
        resp = self._recover_path_and_query(retries=2, delay=0.2)
        if resp is None:
            self._set_disconnected_state()
            return "No mouse detected. Waiting for device..."

        with self._state_lock:
            self.device_online = True
            self.level, self.charging = Common.status_from_response(self.protocol, resp)
            self.status_text = self._status_text()
        self._update_ui_status()
        return f"{self.status_text}\nUpdated at {time.strftime('%H:%M:%S')}"

    def refresh_debug_snapshot(self) -> dict | None:
        """Force a fresh HID read for the debug dialog and update visible state."""
        resp = self._recover_path_and_query()
        with self._state_lock:
            self._last_debug_refresh_time = time.strftime("%H:%M:%S")
        if resp is None:
            self._set_disconnected_state()
            return None

        with self._state_lock:
            self.device_online = True
            self.level, self.charging = Common.status_from_response(self.protocol, resp)
            self.status_text = self._status_text()
        self._update_ui_status()
        return resp

    def _handle_full_charge_notification(self):
        with self._state_lock:
            level = self.level
            charging = self.charging
            already_notified = self._notified_full
            model = self.model
            protocol = self.protocol

        if level == 100 and charging and not already_notified:
            with self._state_lock:
                self._notified_full = True
            self._notify(
                "MouseWatch - Fully Charged",
                f"{protocol.format_model_name(model)} is fully charged",
            )
        elif not charging or level < 100:
            with self._state_lock:
                self._notified_full = False

    def _handle_low_battery_notification(self):
        now = time.time()
        with self._state_lock:
            level = self.level
            threshold = self.threshold
            charging = self.charging
            reminder_interval = self.reminder_interval
            last_notify_time = self._last_notify_time
            model = self.model
            protocol = self.protocol

        if (level <= threshold and not charging
                and (now - last_notify_time) >= reminder_interval):
            with self._state_lock:
                self._last_notify_time = now
            self._notify(
                "MouseWatch - Low Battery",
                f"{protocol.format_model_name(model)} battery is at {level}%",
            )
        elif level > threshold:
            with self._state_lock:
                self._last_notify_time = 0

    def _input_listener(self):
        while not self._stop_event.is_set():
            # Stay alive across protocol switches. For protocols that do not use
            # persistent input reports, idle and re-check later.
            with self._state_lock:
                protocol = self.protocol
                hid_path = self.hid_path

            if not getattr(protocol, "supports_input_listener", False):
                if self._stop_event.wait(2):
                    break
                continue

            current_devices = protocol.discover_devices()
            current_paths = {d["path"] for d in current_devices}

            if hid_path not in current_paths:
                replacement = self._pick_first_available_path(current_devices)
                if replacement is not None:
                    with self._state_lock:
                        self.hid_path = replacement
                    hid_path = replacement
                else:
                    if self._stop_event.wait(5):
                        break
                    self._set_disconnected_state()
                    continue

            try:
                dev = hid.device()
                dev.open_path(hid_path)
                dev.set_nonblocking(False)
            except (OSError, ValueError) as exc:
                print(f"Input listener open error: {exc}")
                if self._stop_event.wait(2):
                    break
                continue

            try:
                while not self._stop_event.is_set():
                    try:
                        raw = dev.read(64, timeout_ms=1000)
                    except (OSError, ValueError) as exc:
                        print(f"Input listener read error: {exc}")
                        break

                    if not raw:
                        continue

                    decoded, parsed = protocol.decode_input_report(list(raw))
                    with self._state_lock:
                        self._last_input_raw = list(raw)
                        self._last_input_decoded = list(decoded)
                        self._last_input_time = time.strftime("%H:%M:%S")

                    if parsed is None:
                        continue

                    with self._state_lock:
                        self.device_online = True
                        battery_level = parsed["battery_level"]
                        old_charging = self.charging
                        self.level = battery_level
                        self.charging = bool(parsed["charging"])
                        self.status_text = self._status_text()
                    self._update_ui_status()

                    with self._state_lock:
                        is_charging = self.charging
                        level = self.level
                        model = self.model
                        device_notifications = self.device_notifications

                    if is_charging != old_charging and device_notifications:
                        msg = (
                            f"{protocol.format_model_name(model)} is charging ({level}%)"
                            if is_charging
                            else f"{protocol.format_model_name(model)} unplugged ({level}%)"
                        )
                        self._notify("MouseWatch", msg)

                    self._handle_full_charge_notification()
            finally:
                try:
                    dev.close()
                except OSError:
                    print("Warning: failed to close input listener HID handle")
                if not self._stop_event.is_set():
                    self._stop_event.wait(2)

    def _device_watcher(self):
        with self._state_lock:
            protocol = self.protocol
        known_paths = {d["path"] for d in protocol.discover_devices()}
        while not self._stop_event.wait(5):
            with self._state_lock:
                protocol = self.protocol
                current_hid_path = self.hid_path
            current_devices = protocol.discover_devices()
            current_paths = {d["path"] for d in current_devices}
            if current_paths != known_paths:
                added = current_paths - known_paths
                removed = known_paths - current_paths
                known_paths = current_paths

                if current_hid_path in removed and current_paths:
                    replacement = self._pick_first_available_path(current_devices)
                    if replacement is not None:
                        with self._state_lock:
                            self.hid_path = replacement

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
        consecutive_failures = 0
        while True:
            self._poll_interrupt.wait(self.interval)
            if self._stop_event.is_set():
                break
            self._poll_interrupt.clear()

            resp = self._recover_path_and_query()
            if resp is None:
                consecutive_failures += 1
                # Avoid brief '?' flicker on transient read failures during
                # provider transitions/hotplug events.
                if consecutive_failures >= 2:
                    self._set_disconnected_state()
                continue

            consecutive_failures = 0

            with self._state_lock:
                self.level, self.charging = Common.status_from_response(self.protocol, resp)
                self.status_text = self._status_text()
                self.device_online = True
            self._update_ui_status()
            self._handle_full_charge_notification()
            self._handle_low_battery_notification()
