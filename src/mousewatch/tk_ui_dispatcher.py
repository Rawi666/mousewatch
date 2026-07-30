import queue
import threading


class TkUiDispatcher:
    """Own a single Tk event thread and marshal all Tk operations onto it."""

    def __init__(self):
        self._queue: queue.Queue = queue.Queue()
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._root = None
        self._stopping = False

    def start(self):
        if self._thread.is_alive():
            return
        self._thread.start()
        self._ready.wait(timeout=2)

    @property
    def root(self):
        return self._root

    def invoke(self, func, *args, **kwargs):
        self._queue.put((func, args, kwargs))

    def stop(self):
        if self._stopping:
            return
        self._stopping = True

        def _shutdown():
            if self._root is not None:
                self._root.quit()

        self.invoke(_shutdown)

    def _run(self):
        import tkinter as tk

        self._root = tk.Tk()
        self._root.withdraw()
        self._ready.set()
        self._pump_queue()
        self._root.mainloop()

    def _pump_queue(self):
        while True:
            try:
                func, args, kwargs = self._queue.get_nowait()
            except queue.Empty:
                break

            try:
                func(*args, **kwargs)
            except Exception as exc:
                print(f"Tk UI dispatch error: {exc}")

        if self._root is not None and not self._stopping:
            self._root.after(50, self._pump_queue)
