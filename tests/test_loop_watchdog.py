"""The loop watchdog writes every thread's stack when the event loop stalls, and only then."""
from __future__ import annotations

import asyncio
import logging
import time

from treg.infra import loop_watchdog


def _blocking_call_in_the_loop(seconds: float) -> None:
    time.sleep(seconds)


async def test_a_stalled_loop_writes_the_stack_of_the_blocking_call(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(loop_watchdog, "_BEAT_S", 0.05)
    with open(tmp_path / "stderr", "w+") as out:
        watchdog = loop_watchdog.LoopWatchdog(0.2, file=out).start()
        try:
            await asyncio.sleep(0.15)
            with caplog.at_level(logging.WARNING, logger="treg.loop_watchdog"):
                _blocking_call_in_the_loop(0.6)
                await asyncio.sleep(0.1)
        finally:
            watchdog.stop()
        out.seek(0)
        dump = out.read()
    assert "most recent call first" in dump
    assert "_blocking_call_in_the_loop" in dump, "the dump names the call that blocked the loop"
    assert any("loop_stall_end" in r.getMessage() for r in caplog.records)


async def test_a_running_loop_writes_nothing(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(loop_watchdog, "_BEAT_S", 0.05)
    with open(tmp_path / "stderr", "w+") as out:
        watchdog = loop_watchdog.LoopWatchdog(0.3, file=out).start()
        with caplog.at_level(logging.WARNING, logger="treg.loop_watchdog"):
            await asyncio.sleep(0.6)
        watchdog.stop()
        out.seek(0)
        assert out.read() == ""
    assert not caplog.records


def test_zero_turns_the_watchdog_off():
    assert loop_watchdog.start_loop_watchdog(0) is None
