try:
    from .common import Common
    from .settings_store import startup_shortcut_exists
except ImportError:
    from common import Common
    from settings_store import startup_shortcut_exists


class SettingsWindow:
    """Tkinter settings window for MouseWatch."""

    _instance = None

    @classmethod
    def open(cls, tray_app, root):
        if cls._instance is not None:
            try:
                cls._instance._window.lift()
                cls._instance._window.focus_force()
                return cls._instance
            except Exception:
                cls._instance = None
        return cls(tray_app, root)

    def __init__(self, tray_app, root):
        SettingsWindow._instance = self
        self._tray_app = tray_app

        import tkinter as tk
        from tkinter import ttk

        self._window = tk.Toplevel(root)
        self._window.title("MouseWatch Settings")
        self._window.resizable(False, False)
        self._window.protocol("WM_DELETE_WINDOW", self._on_close)

        frame = ttk.Frame(self._window, padding=16)
        frame.grid(sticky="nsew")

        row = 0

        ttk.Label(frame, text="Battery threshold (1-100%):").grid(
            row=row, column=0, sticky="w", pady=4)
        self._threshold_var = tk.IntVar(value=tray_app.threshold)
        ttk.Spinbox(frame, from_=1, to=100, textvariable=self._threshold_var,
                    width=8).grid(row=row, column=1, sticky="w", pady=4)

        row += 1
        ttk.Label(frame, text="Reminder interval (60-3600 s):").grid(
            row=row, column=0, sticky="w", pady=4)
        self._reminder_var = tk.IntVar(value=tray_app.reminder_interval)
        ttk.Spinbox(frame, from_=60, to=3600, textvariable=self._reminder_var,
                    width=8).grid(row=row, column=1, sticky="w", pady=4)

        row += 1
        ttk.Label(frame, text="Poll interval (20-3600 s):").grid(
            row=row, column=0, sticky="w", pady=4)
        self._poll_var = tk.IntVar(value=tray_app.interval)
        ttk.Spinbox(frame, from_=20, to=3600, textvariable=self._poll_var,
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
        self._startup_var = tk.BooleanVar(value=startup_shortcut_exists())
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

        self._window.lift()
        self._window.focus_force()

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
        self._window.destroy()
