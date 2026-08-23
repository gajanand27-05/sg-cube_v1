"""The wake success rate was not measuring the wake word.

`/diagnostics/dogfooding` reported 236/470 = 50.2% "wake success" for the
current window, and lifetime 379/2742 = 13.8%. Both numbers are
uninterpretable, because `_start_turn` fires for EVERY trigger — wake word,
barge-in, and follow-up-window capture — and `_run` called
`record_wake(command_handled)` for all three without distinction.

A follow-up window opens after every successful command and tolerates
`_FOLLOWUP_MAX_EMPTY = 2` empty captures before closing. Each of those empty
captures was booked as a FAILED WAKE, with no wake word spoken. So every
command the user got right could contribute up to two failures to the wake
word's own scoreboard.

The trigger source was already known at the trigger site
(`state_manager._voice_trigger_source`, set to "wake"/"followup"/"barge_in"),
it just never reached the ledger. It has to be passed down rather than read
inside the turn: the turn body runs later on a worker thread, and
trigger.py clears `_voice_trigger_source` back to None when the turn ends.

This does not claim the wake word is fine. It makes the number mean what its
name says, so it can be measured at all.
"""
import sys
from pathlib import Path

_project_root = Path(__file__).resolve().parents[1]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))


def _fresh_ledger(tmp_path):
    """A ledger writing to a temp file, never the real dogfooding.json."""
    from backend.core import dogfooding
    led = dogfooding.Ledger(path=tmp_path / "dogfooding.json")
    return led


def test_followup_capture_is_not_a_failed_wake(tmp_path):
    led = _fresh_ledger(tmp_path)
    led.record_wake(False, source="followup")
    snap = led.snapshot()
    assert snap["wake_attempts"] == 0, (
        "an empty follow-up capture was booked against the wake word, which "
        "is how a working wake word scores 50%"
    )
    assert snap["followup_attempts"] == 1


def test_barge_in_is_not_a_failed_wake(tmp_path):
    led = _fresh_ledger(tmp_path)
    led.record_wake(False, source="barge_in")
    snap = led.snapshot()
    assert snap["wake_attempts"] == 0
    assert snap["barge_in_attempts"] == 1


def test_a_real_wake_still_counts(tmp_path):
    led = _fresh_ledger(tmp_path)
    led.record_wake(True, source="wake")
    led.record_wake(False, source="wake")
    snap = led.snapshot()
    assert snap["wake_attempts"] == 2
    assert snap["wake_successes"] == 1


def test_unknown_source_counts_as_a_wake(tmp_path):
    """Fail toward the pessimistic reading. An untagged trigger must not be
    able to quietly improve the score — that is how a metric flatters itself."""
    led = _fresh_ledger(tmp_path)
    led.record_wake(False)
    assert led.snapshot()["wake_attempts"] == 1


def test_start_turn_passes_the_trigger_source_through():
    """The seam. The source is known at the trigger site and must survive on to
    the worker thread, because trigger.py resets _voice_trigger_source to None
    at end of turn — reading it inside the turn body would race."""
    import inspect
    from backend.daemon import wake_word

    src = inspect.getsource(wake_word.WakeWordListener._start_turn)
    assert "source" in src, "_start_turn does not carry a trigger source"

    loop_src = inspect.getsource(wake_word.WakeWordListener)
    assert "source=" in loop_src, (
        "no caller passes source= into _start_turn, so every trigger still "
        "books against the wake word"
    )


if __name__ == "__main__":
    import tempfile
    for _name, _fn in sorted(globals().items()):
        if _name.startswith("test_") and callable(_fn):
            if "tmp_path" in _fn.__code__.co_varnames:
                with tempfile.TemporaryDirectory() as d:
                    _fn(Path(d))
            else:
                _fn()
            print(f"  [PASS] {_name}")
