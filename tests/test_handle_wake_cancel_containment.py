"""A cancel reaching the turn task must not kill the wake-turn thread.

Live, it did:

    Exception in thread wake-turn:
      File "backend/daemon/wake_word.py", line 417, in _run
        result = self.on_wake(audio)
      File "backend/daemon/trigger.py", line 323, in handle_wake
        return asyncio.run(_handle_wake_async(audio_bytes, emit, device_id))
      ...
    asyncio.exceptions.CancelledError

CancelledError is a BaseException, so every `except Exception` on the path
missed it. Two consequences beyond the noise: the turn's final
transition_to(IDLE) never ran, stranding the state machine in SPEAKING, and
_start_turn booked the turn as a FAILED wake in the dogfooding ledger even
though it had spoken a full answer.
"""
import asyncio
import sys
import threading
from pathlib import Path

_project_root = Path(__file__).resolve().parents[1]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from backend.core.state import AssistantState, manager as state_manager
from backend.daemon import trigger


def test_handle_wake_returns_false_instead_of_raising(monkeypatch):
    async def _cancelled(*_a, **_kw):
        state_manager.transition_to(AssistantState.SPEAKING)
        raise asyncio.CancelledError()

    monkeypatch.setattr(trigger, "_handle_wake_async", _cancelled)

    result = trigger.handle_wake(b"\x00\x00")

    assert result is False
    assert state_manager.current == AssistantState.IDLE, (
        "a cancelled turn stranded the state machine in SPEAKING"
    )


def test_cancelled_turn_does_not_kill_the_worker_thread(monkeypatch):
    """The real failure mode: the thread wake_word._start_turn spawned died."""
    async def _cancelled(*_a, **_kw):
        raise asyncio.CancelledError()

    monkeypatch.setattr(trigger, "_handle_wake_async", _cancelled)

    escaped: list[BaseException] = []
    finished = threading.Event()

    def _run():
        try:
            trigger.handle_wake(b"\x00\x00")
        except BaseException as e:  # noqa: BLE001 - that is the thing under test
            escaped.append(e)
        finally:
            finished.set()

    t = threading.Thread(target=_run, name="wake-turn")
    t.start()
    assert finished.wait(timeout=10), "worker thread hung"
    t.join(timeout=5)

    assert not escaped, f"exception escaped the turn thread: {escaped!r}"


def teardown_function(_fn):
    state_manager.transition_to(AssistantState.IDLE)
