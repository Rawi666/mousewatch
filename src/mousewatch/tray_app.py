import threading

from common import Common
from common import safe_notify
from debug_window import DebugWindow
from icon_factory import create_windows_battery_icon, create_windows_unknown_battery_icon
from mw_platform import IS_LINUX
from settings_window import SettingsWindow


class TrayApp(Common):
    """System tray application for MouseWatch."""

    def __init__(self, protocol, model: str, hid_path: bytes | None, initial_resp: dict | None,
                 settings: dict, available_protocols: list | None = None):
        self.protocol = protocol
        self.available_protocols = available_protocols or [protocol]
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
        if initial_resp is None:
            self.level = 0
            self.charging = False
            self.device_online = False
        else:
            self.level, self.charging = Common.status_from_response(self.protocol, initial_resp)
            self.device_online = bool(initial_resp.get("device_online", True))
        self.status_text = self._status_text()
        self._stop_event = threading.Event()
        self._poll_interrupt = threading.Event()
        self.icon = None
        self._last_input_raw = None
        self._last_input_decoded = None
        self._last_input_time = None
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
            if self.device_online:
                self.icon.icon = create_windows_battery_icon(self.level, self.threshold)
            else:
                self.icon.icon = create_windows_unknown_battery_icon()
            self.icon.title = self.status_text

    def _notify(self, title: str, message: str):
        safe_notify(title, message, sound=self.notification_sound)

    def _on_status(self, icon, item):
        _ = icon
        _ = item
        msg = self._refresh_status()
        self._notify("MouseWatch", msg)

    def _on_settings(self, icon, item):
        _ = icon
        _ = item
        threading.Thread(target=SettingsWindow, args=(self,), daemon=True).start()

    def _on_debug(self, icon, item):
        _ = icon
        _ = item
        threading.Thread(target=DebugWindow, args=(self,), daemon=True).start()

    def _on_quit(self, icon, item):
        _ = icon
        _ = item
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
        ttk.Label(frame, textvariable=status_var).grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 8)
        )

        def refresh_click():
            msg = self._refresh_status()
            status_var.set(self.status_text)
            self._notify("MouseWatch", msg)

        ttk.Button(frame, text="Refresh", command=refresh_click).grid(
            row=1, column=0, sticky="ew", padx=(0, 4), pady=4
        )
        ttk.Button(frame, text="Settings", command=lambda: self._on_settings(None, None)).grid(
            row=1, column=1, sticky="ew", padx=(4, 0), pady=4
        )
        ttk.Button(frame, text="Debug", command=lambda: self._on_debug(None, None)).grid(
            row=2, column=0, sticky="ew", padx=(0, 4), pady=4
        )
        ttk.Button(frame, text="Quit", command=self._on_quit_direct).grid(
            row=2, column=1, sticky="ew", padx=(4, 0), pady=4
        )

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

        if self.device_online:
            image = create_windows_battery_icon(self.level, self.threshold)
        else:
            image = create_windows_unknown_battery_icon()
        self.icon = pystray.Icon(
            "MouseWatch",
            image,
            title=self.status_text,
            menu=self._create_menu(),
        )

        if IS_LINUX and not self._menu_supported:
            print("Tray backend has no menu support on this Linux session.")
            print("Opening MouseWatch control window for Settings/Debug/Quit.")
            threading.Thread(target=self._run_fallback_control_window, daemon=True).start()

        poll_thread = threading.Thread(target=self._poll_loop, daemon=True)
        poll_thread.start()

        if self.protocol.supports_input_listener:
            input_thread = threading.Thread(target=self._input_listener, daemon=True)
            input_thread.start()

        watcher_thread = threading.Thread(target=self._device_watcher, daemon=True)
        watcher_thread.start()

        self.icon.run()
