import os
import threading
import time
import traceback

try:
    from .common import Common
    from .common import safe_notify
    from .debug_window import DebugWindow
    from .icon_factory import create_windows_battery_icon, create_windows_unknown_battery_icon
    from .mw_platform import IS_LINUX, IS_WINDOWS
    from .settings_window import SettingsWindow
    from .tk_ui_dispatcher import TkUiDispatcher
except ImportError:
    from common import Common
    from common import safe_notify
    from debug_window import DebugWindow
    from icon_factory import create_windows_battery_icon, create_windows_unknown_battery_icon
    from mw_platform import IS_LINUX, IS_WINDOWS
    from settings_window import SettingsWindow
    from tk_ui_dispatcher import TkUiDispatcher


class TrayApp(Common):
    """System tray application for MouseWatch."""

    def __init__(self, protocol, model: str, hid_path: bytes | None, initial_resp: dict | None,
                 settings: dict, available_protocols: list | None = None):
        Common.init_runtime_state(
            self,
            protocol,
            model,
            hid_path,
            initial_resp,
            settings,
            available_protocols=available_protocols,
        )
        self.icon = None
        self._menu_supported = True
        self._status_refresh_active = False
        self._status_refresh_lock = threading.Lock()
        self._ui_dispatcher: TkUiDispatcher | None = None
        self._control_window = None
        self._debug_enabled = os.environ.get("MOUSEWATCH_DEBUG", "").strip().lower() in {
            "1", "true", "yes", "on",
        }

    def _debug_log(self, message: str):
        if not self._debug_enabled:
            return
        print(f"[{time.strftime('%H:%M:%S')}][MouseWatch][tray] {message}", flush=True)

    def _ensure_ui_dispatcher(self):
        if self._ui_dispatcher is None:
            self._ui_dispatcher = TkUiDispatcher()
            self._ui_dispatcher.start()

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
        icon_notify = getattr(self.icon, "notify", None)
        has_icon_notify = callable(icon_notify)
        self._debug_log(
            f"notify begin title={title!r} sound={self.notification_sound} "
            f"device_online={self.device_online} status={self.status_text!r} "
            f"has_icon_notify={has_icon_notify}"
        )
        if IS_WINDOWS and has_icon_notify:
            try:
                icon_notify(message, title=title)
                self._debug_log("notify via pystray icon.notify succeeded")
                return
            except Exception as exc:
                self._debug_log(f"notify via pystray icon.notify failed: {exc!r}")
                traceback.print_exc()

        ok = safe_notify(title, message, sound=self.notification_sound)
        self._debug_log(f"notify via safe_notify returned {ok}")
        if ok:
            return

        if has_icon_notify:
            try:
                icon_notify(message, title=title)
                self._debug_log("notify fallback via pystray icon.notify succeeded")
                return
            except Exception as exc:
                self._debug_log(f"notify fallback via pystray icon.notify failed: {exc!r}")
                traceback.print_exc()

        print(f"{title}: {message}")

    def _install_windows_click_refresh(self):
        """Route tray left-click events to the Status refresh action on Windows."""
        if not IS_WINDOWS or self.icon is None:
            self._debug_log("windows click hook skipped (not windows or icon missing)")
            return

        handlers = getattr(self.icon, "_message_handlers", None)
        if not isinstance(handlers, dict):
            self._debug_log("windows click hook skipped (_message_handlers missing)")
            return

        try:
            from pystray._util import win32
        except Exception:
            self._debug_log("windows click hook skipped (pystray._util.win32 unavailable)")
            return

        # Some pystray builds do not expose all constants; use stable numeric fallbacks.
        wm_notify = getattr(win32, "WM_NOTIFY", None)
        if wm_notify is None:
            for code, handler in handlers.items():
                if getattr(handler, "__name__", "") == "_on_notify":
                    wm_notify = code
                    break
        if wm_notify is None:
            self._debug_log("windows click hook skipped (WM_NOTIFY id unavailable)")
            return

        wm_lbuttonup = getattr(win32, "WM_LBUTTONUP", 0x0202)
        wm_lbuttondblclk = getattr(win32, "WM_LBUTTONDBLCLK", 0x0203)
        nin_select = getattr(win32, "NIN_SELECT", 0x0400)
        nin_keyselect = getattr(win32, "NIN_KEYSELECT", 0x0401)

        previous_handler = handlers.get(wm_notify)
        if previous_handler is None:
            self._debug_log("windows click hook skipped (WM_NOTIFY handler missing)")
            return

        self._debug_log(
            "windows click hook installed "
            f"(wm_notify=0x{int(wm_notify):X}, lbuttonup=0x{wm_lbuttonup:X}, "
            f"lbuttondblclk=0x{wm_lbuttondblclk:X}, nin_select=0x{nin_select:X}, "
            f"nin_keyselect=0x{nin_keyselect:X})"
        )

        def _on_notify(wparam, lparam):
            _ = wparam
            # WM_MOUSEMOVE (0x0200) is very noisy over the tray icon.
            if int(lparam) != 0x0200:
                self._debug_log(f"WM_NOTIFY lparam=0x{int(lparam):X}")
            if lparam in (wm_lbuttonup, wm_lbuttondblclk, nin_select, nin_keyselect):
                self._debug_log("tray left click event routed to status refresh")
                self._on_status(self.icon, None)
                return
            previous_handler(wparam, lparam)

        handlers[wm_notify] = _on_notify

    def _on_status(self, icon, item):
        _ = icon
        _ = item
        self._debug_log("status action requested")
        with self._status_refresh_lock:
            if self._status_refresh_active:
                self._debug_log("status refresh skipped (already active)")
                return
            self._status_refresh_active = True
            self._debug_log("status refresh worker starting")

        def _refresh_worker():
            try:
                msg = self._refresh_status()
                self._debug_log(f"status refresh result: {msg!r}")
                self._notify("MouseWatch", msg)
            except Exception as exc:
                self._debug_log(f"status refresh worker failed: {exc!r}")
                traceback.print_exc()
            finally:
                with self._status_refresh_lock:
                    self._status_refresh_active = False
                self._debug_log("status refresh worker finished")

        threading.Thread(target=_refresh_worker, daemon=True).start()

    def _on_settings(self, icon, item):
        _ = icon
        _ = item
        self._ensure_ui_dispatcher()
        assert self._ui_dispatcher is not None
        self._ui_dispatcher.invoke(SettingsWindow.open, self, self._ui_dispatcher.root)

    def _on_debug(self, icon, item):
        _ = icon
        _ = item
        self._ensure_ui_dispatcher()
        assert self._ui_dispatcher is not None
        self._ui_dispatcher.invoke(DebugWindow.open, self, self._ui_dispatcher.root)

    def _on_quit(self, icon, item):
        _ = icon
        _ = item
        self._stop_event.set()
        self._poll_interrupt.set()
        if self._ui_dispatcher is not None:
            self._ui_dispatcher.stop()
        icon.stop()

    def _on_quit_direct(self):
        self._stop_event.set()
        self._poll_interrupt.set()
        if self._ui_dispatcher is not None:
            self._ui_dispatcher.stop()
        if self.icon:
            self.icon.stop()

    def _open_fallback_control_window(self):
        """Show controls when tray backend cannot render context menus."""
        if self._control_window is not None:
            try:
                self._control_window.lift()
                self._control_window.focus_force()
                return
            except Exception:
                self._control_window = None

        import tkinter as tk
        from tkinter import ttk

        assert self._ui_dispatcher is not None
        root = tk.Toplevel(self._ui_dispatcher.root)
        root.title("MouseWatch")
        root.resizable(False, False)
        self._control_window = root

        def _on_close():
            self._control_window = None
            root.destroy()

        root.protocol("WM_DELETE_WINDOW", _on_close)

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
            with self._state_lock:
                status_var.set(self.status_text)
            if not self._stop_event.is_set():
                root.after(1000, ticker)
            else:
                root.destroy()
                self._control_window = None

        root.after(1000, ticker)
        root.lift()
        root.focus_force()

    def run(self):
        import pystray

        self._debug_log("tray app run() entered")

        self._menu_supported = bool(getattr(pystray.Icon, "HAS_MENU", True))
        self._debug_log(f"pystray HAS_MENU={self._menu_supported}")

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
        self._debug_log("pystray icon created")
        self._install_windows_click_refresh()

        if IS_LINUX and not self._menu_supported:
            print("Tray backend has no menu support on this Linux session.")
            print("Opening MouseWatch control window for Settings/Debug/Quit.")
            self._ensure_ui_dispatcher()
            assert self._ui_dispatcher is not None
            self._ui_dispatcher.invoke(self._open_fallback_control_window)

        poll_thread = threading.Thread(target=self._poll_loop, daemon=True)
        poll_thread.start()

        input_thread = threading.Thread(target=self._input_listener, daemon=True)
        input_thread.start()

        watcher_thread = threading.Thread(target=self._device_watcher, daemon=True)
        watcher_thread.start()

        self._debug_log("starting pystray event loop")
        self.icon.run()
