from common import Common
from settings_store import startup_shortcut_exists


class SettingsWindow:
    """Tkinter settings window for MouseWatch."""

    _instance = None

    def __init__(self, tray_app):
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
