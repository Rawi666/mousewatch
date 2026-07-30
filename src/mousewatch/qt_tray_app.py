import subprocess
import sys
import threading
import time

try:
    from .common import Common
    from .icon_factory import create_qt_battery_icon, create_qt_unknown_battery_icon
    from .mw_platform import (
        IS_WINDOWS,
        QAction,
        QApplication,
        QMenu,
        QObject,
        QSystemTrayIcon,
        Signal,
    )
    from .qt_debug_dialog import QtDebugDialog
    from .qt_settings_dialog import QtSettingsDialog
except ImportError:
    from common import Common
    from icon_factory import create_qt_battery_icon, create_qt_unknown_battery_icon
    from mw_platform import (
        IS_WINDOWS,
        QAction,
        QApplication,
        QMenu,
        QObject,
        QSystemTrayIcon,
        Signal,
    )
    from qt_debug_dialog import QtDebugDialog
    from qt_settings_dialog import QtSettingsDialog


if not IS_WINDOWS and QObject is not None:
    class QtTrayApp(QObject, Common):
        """Qt system tray application for MouseWatch."""

        status_changed = Signal(int, bool, str)
        notification_requested = Signal(str, str)

        def __init__(self, protocol, model: str, hid_path: bytes | None, initial_resp: dict | None,
                     settings: dict, is_autostart: bool = False, available_protocols: list | None = None):
            super().__init__()
            self.is_autostart = is_autostart
            Common.init_runtime_state(
                self,
                protocol,
                model,
                hid_path,
                initial_resp,
                settings,
                available_protocols=available_protocols,
            )
            self._settings_dialog = None
            self._debug_dialog = None
            self._status_refresh_active = False
            self._status_refresh_lock = threading.Lock()

            existing = QApplication.instance()
            if isinstance(existing, QApplication):
                app = existing
            else:
                app = QApplication(sys.argv)
            self._app = app
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
            if self.device_online:
                self.tray.setIcon(create_qt_battery_icon(self.level, self.threshold))
            else:
                self.tray.setIcon(create_qt_unknown_battery_icon())
            self.tray.setToolTip(self.status_text)
            self.tray.setVisible(True)

        def _update_ui_status(self):
            self.status_changed.emit(self.level, self.charging, self.status_text)

        def _show_notification(self, title: str, message: str):
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
            _ = checked
            with self._status_refresh_lock:
                if self._status_refresh_active:
                    return
                self._status_refresh_active = True

            def _refresh_worker():
                try:
                    msg = self._refresh_status()
                    self._notify("MouseWatch", msg)
                finally:
                    with self._status_refresh_lock:
                        self._status_refresh_active = False

            threading.Thread(target=_refresh_worker, daemon=True).start()

        def _on_settings(self, checked: bool = False):
            _ = checked
            dialog = QtSettingsDialog(self)
            dialog.show()
            dialog.raise_()
            dialog.activateWindow()
            self._settings_dialog = dialog

        def _on_debug(self, checked: bool = False):
            _ = checked
            dialog = QtDebugDialog(self)
            dialog.show()
            dialog.raise_()
            dialog.activateWindow()
            self._debug_dialog = dialog

        def _on_quit(self, checked: bool = False):
            _ = checked
            self._stop_event.set()
            self._poll_interrupt.set()
            self.tray.hide()
            self._app.quit()

        def run(self):
            if self.is_autostart:
                for _ in range(60):
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
else:
    class QtTrayApp:
        def __init__(self, protocol, model: str, hid_path: bytes | None, initial_resp: dict | None,
                     settings: dict, is_autostart: bool = False, available_protocols: list | None = None):
            _ = (protocol, model, hid_path, initial_resp, settings, is_autostart, available_protocols)

        def run(self):
            raise RuntimeError("QtTrayApp is unavailable (Linux with PySide6 required)")
