from types import SimpleNamespace

import mousewatch.tk_ui_dispatcher as tk_mod
from mousewatch.tk_ui_dispatcher import TkUiDispatcher


class FakeRoot:
    def __init__(self):
        self.after_calls = []
        self.quit_called = False
        self.withdraw_called = False
        self.mainloop_called = False

    def after(self, delay, callback):
        self.after_calls.append((delay, callback))

    def quit(self):
        self.quit_called = True

    def withdraw(self):
        self.withdraw_called = True

    def mainloop(self):
        self.mainloop_called = True


class FakeThread:
    def __init__(self, alive=False):
        self._alive = alive
        self.started = False

    def is_alive(self):
        return self._alive

    def start(self):
        self.started = True


class FakeEvent:
    def __init__(self):
        self.wait_calls = []
        self.set_calls = 0

    def wait(self, timeout=None):
        self.wait_calls.append(timeout)
        return True

    def set(self):
        self.set_calls += 1



def test_start_noop_when_thread_already_alive():
    dispatcher = TkUiDispatcher()
    dispatcher._thread = FakeThread(alive=True)

    dispatcher.start()

    assert dispatcher._thread.started is False


def test_start_starts_thread_and_waits_for_ready():
    dispatcher = TkUiDispatcher()
    dispatcher._thread = FakeThread(alive=False)
    dispatcher._ready = FakeEvent()

    dispatcher.start()

    assert dispatcher._thread.started is True
    assert dispatcher._ready.wait_calls == [2]


def test_invoke_and_pump_queue_executes_task_and_reschedules():
    dispatcher = TkUiDispatcher()
    root = FakeRoot()
    dispatcher._root = root

    calls = []
    dispatcher.invoke(lambda a, b: calls.append(a + b), 2, 3)
    dispatcher._pump_queue()

    assert calls == [5]
    assert root.after_calls and root.after_calls[0][0] == 50


def test_pump_queue_reports_callback_exceptions(capsys):
    dispatcher = TkUiDispatcher()
    root = FakeRoot()
    dispatcher._root = root

    def bad():
        raise RuntimeError("boom")

    dispatcher.invoke(bad)
    dispatcher._pump_queue()

    out = capsys.readouterr().out
    assert "Tk UI dispatch error: boom" in out


def test_stop_enqueues_shutdown_and_quits_root():
    dispatcher = TkUiDispatcher()
    root = FakeRoot()
    dispatcher._root = root

    dispatcher.stop()
    dispatcher._pump_queue()

    assert dispatcher._stopping is True
    assert root.quit_called is True


def test_run_initializes_root_and_enters_mainloop(monkeypatch):
    dispatcher = TkUiDispatcher()
    root = FakeRoot()
    pump_calls = []

    monkeypatch.setattr(dispatcher, "_pump_queue", lambda: pump_calls.append(True))

    fake_tk_module = SimpleNamespace(Tk=lambda: root)
    monkeypatch.setitem(__import__("sys").modules, "tkinter", fake_tk_module)

    dispatcher._run()

    assert dispatcher.root is root
    assert root.withdraw_called is True
    assert root.mainloop_called is True
    assert pump_calls == [True]
