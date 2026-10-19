"""Runs asyncio coroutines (wyzeapy) on a dedicated background thread.

Qt widgets must never block on network I/O, and wyzeapy is async-only, so
every Wyze call is submitted here as a coroutine. Results are delivered back
to the GUI thread through the ``task_done`` signal.
"""
from __future__ import annotations

import asyncio
import threading
from concurrent.futures import Future
from typing import Any, Callable, Coroutine, Optional

from PySide6.QtCore import QObject, QThread, Signal

# Callback invoked on the GUI thread: on_done(ok, result, error_message).
OnDone = Callable[[bool, Any, str], None]


class AsyncRunner(QThread):
    task_done = Signal(str, bool, object, str)  # task_id, ok, result, error

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._ready = threading.Event()
        self._callbacks: dict[str, OnDone] = {}
        self._counter = 0
        self._lock = threading.Lock()
        self.task_done.connect(self._dispatch)

    def run(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._ready.set()
        try:
            self._loop.run_forever()
        finally:
            self._loop.close()

    def submit(
        self,
        name: str,
        coro: Coroutine[Any, Any, Any],
        on_done: OnDone | None = None,
    ) -> str:
        """Schedule *coro* on the background loop. Returns a task id."""
        if not self._ready.wait(timeout=15):
            raise RuntimeError("AsyncRunner event loop did not start")
        assert self._loop is not None
        with self._lock:
            self._counter += 1
            task_id = f"{name}-{self._counter}"
            if on_done is not None:
                self._callbacks[task_id] = on_done
        future: Future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        future.add_done_callback(lambda f, tid=task_id: self._finish(tid, f))
        return task_id

    def _finish(self, task_id: str, future: Future) -> None:
        # Runs on the event-loop thread; the signal hop moves us to the GUI thread.
        try:
            result = future.result()
            ok, error = True, ""
        except Exception as exc:  # noqa: BLE001 - surfaced to the UI, not swallowed
            result, ok, error = None, False, f"{type(exc).__name__}: {exc}"
        self.task_done.emit(task_id, ok, result, error)

    def _dispatch(self, task_id: str, ok: bool, result: Any, error: str) -> None:
        # Runs on the GUI thread thanks to the queued signal connection.
        with self._lock:
            callback = self._callbacks.pop(task_id, None)
        if callback is not None:
            callback(ok, result, error)

    def stop(self) -> None:
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._loop.stop)
        self.wait(5000)
