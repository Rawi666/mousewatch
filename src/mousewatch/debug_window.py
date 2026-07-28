from common import Common


class DebugWindow:
    """Tkinter debug window showing raw HID data."""

    _instance = None

    def __init__(self, tray_app):
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
