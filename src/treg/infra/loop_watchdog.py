"""Write every thread's stack when the event loop stops running callbacks.

The loop re-arms `faulthandler.dump_traceback_later` every `_BEAT_S`. When a beat is `threshold_s`
late, faulthandler's own C thread writes all Python stacks to stderr: it needs neither
the GIL nor the logging locks, so it also reports a loop stuck in C code or behind a held logging
lock. One dump per stall; when the loop runs again it logs how long it stood still.
"""
from __future__ import annotations

import asyncio
import faulthandler
import logging
import sys
import time
from typing import TextIO

# CPython starts a new watchdog thread on every re-arm, so the beat stays coarse.
_BEAT_S = 1.0

log = logging.getLogger("treg.loop_watchdog")


class LoopWatchdog:
    def __init__(self, threshold_s: float, *, file: TextIO | None = None) -> None:
        self._threshold = threshold_s
        self._file = file if file is not None else sys.stderr
        self._last = time.monotonic()
        self._handle: asyncio.TimerHandle | None = None

    def start(self) -> "LoopWatchdog":
        self._last = time.monotonic()
        self._tick()
        return self

    def _tick(self) -> None:
        now = time.monotonic()
        stalled = now - self._last - _BEAT_S
        if stalled >= self._threshold:
            log.warning("loop_stall_end stalled_ms=%d threshold_s=%g; the stacks written at the "
                        "threshold precede this line", int(stalled * 1000), self._threshold)
        self._last = now
        # Armed past the next beat, so the dump and the stall line count the same stall.
        faulthandler.dump_traceback_later(self._threshold + _BEAT_S, exit=False, file=self._file)
        self._handle = asyncio.get_running_loop().call_later(_BEAT_S, self._tick)

    def stop(self) -> None:
        if self._handle is not None:
            self._handle.cancel()
            self._handle = None
        faulthandler.cancel_dump_traceback_later()


def start_loop_watchdog(threshold_s: float) -> LoopWatchdog | None:
    """`None` when disabled (`threshold_s <= 0`) or when stderr has no file descriptor."""
    if threshold_s <= 0:
        return None
    try:
        return LoopWatchdog(threshold_s).start()
    except Exception:  # noqa: BLE001 - a missing diagnostic must never stop the service
        log.warning("loop watchdog unavailable", exc_info=True)
        return None


def stop_loop_watchdog(watchdog: LoopWatchdog | None) -> None:
    if watchdog is not None:
        try:
            watchdog.stop()
        except Exception:  # noqa: BLE001 - shutdown keeps its original exception
            pass
