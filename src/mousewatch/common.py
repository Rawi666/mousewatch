import threading
import time

from mw_platform import IS_WINDOWS, hid
from settings_store import save_settings, set_startup


class Common:
    """Shared cross-platform app logic used by both tray implementations."""

    model: str
    hid_path: bytes
    protocol: object
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
    _last_input_raw: list[int] | None
    _last_input_decoded: list[int] | None
    _last_input_time: str | None
    _last_debug_refresh_time: str | None

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
        set_startup(settings["start_with_windows"])

    @staticmethod
    def build_debug_lines(app, snapshot: dict | None, section_title: str = "Last E2 Input Report") -> list[str]:
        lines = []
        lines.append(f"Model:   {app.protocol.format_model_name(app.model)}")
        lines.append(f"Battery: {app.level}%")
        lines.append(f"Status:  {'Charging' if app.charging else 'Wireless'}")
        if app._last_debug_refresh_time:
            lines.append(f"Refreshed: {app._last_debug_refresh_time}")
        lines.append("")
        lines.append(section_title)

        if app._last_input_time:
            lines.append(f"Time:    {app._last_input_time}")
            raw = app._last_input_raw
            dec = app._last_input_decoded
            if raw is not None:
                lines.append(f"Raw:     {' '.join(f'{b:02X}' for b in raw)}")
            if dec is not None:
                lines.append(f"Decoded: {' '.join(f'{b:02X}' for b in dec)}")
                lines.append("")
                app.protocol.append_debug_input_details(lines, dec)
        else:
            lines.append("No input reports received yet.")

        lines.append("")
        if snapshot is None:
            lines.append("Manual refresh: no response")
        else:
            lines.append(f"Manual refresh: battery {snapshot['battery_level']}%")

        return lines

    def _status_text(self) -> str:
        return Common.format_status_text(self.protocol, self.model, self.level, self.charging)

    def apply_settings(self, settings: dict):
        Common.apply_settings_to_app(self, settings)

    def _refresh_status(self) -> str:
        resp = Common.query_battery_retry(self.protocol, self.hid_path)
        if resp is None:
            return "Failed to read battery status"

        self.level, self.charging = Common.status_from_response(self.protocol, resp)
        self.status_text = self._status_text()
        self._update_ui_status()
        return f"{self.status_text}\nUpdated at {time.strftime('%H:%M:%S')}"

    def refresh_debug_snapshot(self) -> dict | None:
        """Force a fresh HID read for the debug dialog and update visible state."""
        resp = Common.query_battery_retry(self.protocol, self.hid_path)
        self._last_debug_refresh_time = time.strftime("%H:%M:%S")
        if resp is None:
            return None

        self.level, self.charging = Common.status_from_response(self.protocol, resp)
        self.status_text = self._status_text()
        self._update_ui_status()
        return resp

    def _handle_full_charge_notification(self):
        if self.level == 100 and self.charging and not self._notified_full:
            self._notified_full = True
            self._notify(
                "MouseWatch - Fully Charged",
                f"{self.protocol.format_model_name(self.model)} is fully charged",
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
                f"{self.protocol.format_model_name(self.model)} battery is at {self.level}%",
            )
        elif self.level > self.threshold:
            self._last_notify_time = 0

    def _input_listener(self):
        while not self._stop_event.is_set():
            current_devices = self.protocol.discover_devices()
            current_paths = {d["path"] for d in current_devices}

            if self.hid_path not in current_paths:
                if current_paths:
                    self.hid_path = next(iter(current_paths))
                else:
                    if self._stop_event.wait(5):
                        break
                    continue

            try:
                dev = hid.device()
                dev.open_path(self.hid_path)
                dev.set_nonblocking(False)
            except Exception:
                if self._stop_event.wait(2):
                    break
                continue

            try:
                while not self._stop_event.is_set():
                    try:
                        raw = dev.read(64, timeout_ms=1000)
                    except Exception:
                        break

                    if not raw:
                        continue

                    decoded, parsed = self.protocol.decode_input_report(list(raw))
                    self._last_input_raw = list(raw)
                    self._last_input_decoded = list(decoded)
                    self._last_input_time = time.strftime("%H:%M:%S")

                    if parsed is None:
                        continue

                    battery_level = parsed["battery_level"]

                    old_charging = self.charging
                    self.level = battery_level
                    self.charging = bool(parsed["charging"])
                    self.status_text = self._status_text()
                    self._update_ui_status()

                    if self.charging != old_charging and self.device_notifications:
                        msg = (
                            f"{self.protocol.format_model_name(self.model)} is charging ({self.level}%)"
                            if self.charging
                            else f"{self.protocol.format_model_name(self.model)} unplugged ({self.level}%)"
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
        known_paths = {d["path"] for d in self.protocol.discover_devices()}
        while not self._stop_event.wait(5):
            current_paths = {d["path"] for d in self.protocol.discover_devices()}
            if current_paths != known_paths:
                added = current_paths - known_paths
                removed = known_paths - current_paths
                known_paths = current_paths

                if self.hid_path in removed and current_paths:
                    self.hid_path = next(iter(current_paths))

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

            current_devices = self.protocol.discover_devices()
            current_paths = {d["path"] for d in current_devices}
            if self.hid_path not in current_paths:
                if current_paths:
                    self.hid_path = next(iter(current_paths))
                else:
                    continue

            resp = Common.query_battery_retry(self.protocol, self.hid_path)
            if resp is None:
                continue

            self.level, self.charging = Common.status_from_response(self.protocol, resp)
            self.status_text = self._status_text()
            self._update_ui_status()
            self._handle_full_charge_notification()
            self._handle_low_battery_notification()
