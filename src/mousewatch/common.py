import threading
import time

from hid_protocol import find_mchose_devices, query_battery, xor_decode
from mw_platform import IS_WINDOWS, hid
from settings_store import save_settings, set_startup


class Common:
    """Shared cross-platform app logic used by both tray implementations."""

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
        set_startup(settings["start_with_windows"])

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
            current_devices = find_mchose_devices()
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

            current_devices = find_mchose_devices()
            current_paths = {d["path"] for d in current_devices}
            if self.hid_path not in current_paths:
                if current_paths:
                    self.hid_path = next(iter(current_paths))
                else:
                    continue

            resp = Common.query_battery_retry(self.hid_path)
            if resp is None:
                continue

            self.level, self.charging = Common.status_from_response(resp)
            self.status_text = self._status_text()
            self._update_ui_status()
            self._handle_full_charge_notification()
            self._handle_low_battery_notification()
