"""Count barge-ins, and how many of them were the assistant interrupting itself.

T-barge-in-tuning has been blocked on data since Phase 4, and its instruction
is explicit: "Do not pre-tune against synthetic mic input. Guaranteed to
require a re-tune the moment you use it live." That leaves counting real use
as the only way to answer it.

Until b8e379a the question could not even be asked — the listener discarded
every mic frame while speaking, so barge-in never fired at all. Now that it
can, the number that decides the ticket is what FRACTION of barge-ins were
the assistant's own TTS bleeding into the mic. A high ratio means the
threshold or AEC needs work; a low one means barge-in behaves and the ticket
closes.

The two counters are recorded at different moments on purpose, and that is
the thing worth testing: the total at the interruption (the only point every
barge-in passes through — some never reach Whisper), the self-flag only after
transcription identifies the echo.
"""
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

_project_root = Path(__file__).resolve().parents[1]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))


@pytest.fixture()
def ledger(tmp_path):
    from backend.core.dogfooding import Ledger
    return Ledger(path=tmp_path / "dogfooding.json")


def test_counters_start_absent_not_zero(ledger):
    """None means "never measured"; 0% means "measured, and none were self".
    Conflating them would read as "barge-in is perfect" before it has ever
    fired once."""
    assert ledger.snapshot()["rates"]["barge_in_self_pct"] is None


def test_a_barge_in_is_counted(ledger):
    ledger.record_barge_in()
    snap = ledger.snapshot()
    assert snap["barge_ins"] == 1
    assert snap["rates"]["barge_in_self_pct"] == 0.0, (
        "one real barge-in and no self-interrupts is 0%, not None"
    )


def test_self_interrupts_are_a_subset_not_a_separate_total(ledger):
    """The bug this guards: recording the self case as its own barge-in would
    double-count the denominator and halve the reported ratio."""
    ledger.record_barge_in()
    ledger.record_barge_in_self()
    ledger.record_barge_in()
    snap = ledger.snapshot()
    assert snap["barge_ins"] == 2
    assert snap["barge_in_self"] == 1
    assert snap["rates"]["barge_in_self_pct"] == 50.0


def test_both_counters_are_windowed(ledger):
    """They have to survive into the window, or the data-gated ticket reads
    lifetime numbers spanning builds where barge-in could not fire at all."""
    ledger.record_barge_in()
    ledger.record_barge_in_self()
    assert ledger.snapshot()["window"]["barge_ins"] == 1
    assert ledger.snapshot()["window"]["barge_in_self"] == 1
    ledger.reset_window(label="test")
    assert ledger.snapshot()["window"]["barge_ins"] == 0
    assert ledger.snapshot()["window_rates"]["barge_in_self_pct"] is None


def test_they_persist_across_a_restart(ledger, tmp_path):
    from backend.core.dogfooding import Ledger
    ledger.record_barge_in()
    ledger.record_barge_in_self()
    reopened = Ledger(path=tmp_path / "dogfooding.json")
    assert reopened.snapshot()["barge_ins"] == 1
    assert reopened.snapshot()["barge_in_self"] == 1


# ── the recording sites actually fire ──────────────────────────────────

def test_on_barge_in_records_the_interruption():
    """Wiring guard. A counter nobody increments reads as "barge-in never
    fires", which is the exact wrong conclusion to draw tonight."""
    from backend.daemon.trigger import on_barge_in
    with patch("backend.daemon.trigger.dogfooding_ledger") as led, \
         patch("backend.daemon.trigger.stop_speech"), \
         patch("backend.daemon.trigger.get_sentence_queue"), \
         patch("backend.daemon.trigger.commander"), \
         patch("backend.daemon.trigger.get_bus"), \
         patch("backend.daemon.trigger.threading.Thread"), \
         patch("backend.daemon.trigger.state_manager"):
        on_barge_in(rms=1234.0, emit=None)
    led.record_barge_in.assert_called_once()


def test_the_echo_drop_records_a_self_interrupt_only_on_a_barge_in_turn():
    """A dropped echo on a WAKE turn is not a self-interrupt — the user did
    address the assistant, Whisper just picked up the tail of the reply.
    Counting those would inflate the ratio and condemn barge-in unfairly."""
    import inspect
    from backend.daemon import trigger

    src = inspect.getsource(trigger._handle_wake_async)
    assert "record_barge_in_self" in src
    idx = src.index("record_barge_in_self")
    guard = src.rindex('_voice_trigger_source == "barge_in"', 0, idx)
    assert guard > src.index("was_recently_spoken"), (
        "the self-interrupt counter must sit inside the echo branch AND "
        "behind the barge_in source check"
    )


def test_the_suite_is_not_writing_to_the_production_ledger():
    """Guard on conftest's session fixture.

    This was not hypothetical: a freshly started backend reported
    barge_in_self_pct 0.0 after a barge-in that never happened, because
    tests/test_barge_in.py calls the real on_barge_in and the count went into
    backend/database/dogfooding.json. Anything driving listen() writes a wake
    attempt the same way.

    The damage is worse than a wrong count: inflating wake_attempts against a
    real wake_successes drags the measured wake success rate DOWN, so the
    number the data-gated tickets are read from is wrong in a direction that
    looks like a genuine regression.
    """
    from backend.core.dogfooding import ledger

    production = (Path(__file__).resolve().parents[1]
                  / "backend" / "database" / "dogfooding.json")
    assert Path(ledger._path).resolve() != production.resolve(), (
        "the ledger singleton still points at the production file; a test that "
        "exercises a recording site will corrupt real dogfooding data"
    )


def test_recording_through_the_singleton_stays_in_the_sandbox():
    """The in-place redirect has to cover the holders that imported the object
    rather than the module — trigger.py and wake_word.py both do."""
    from backend.core.dogfooding import ledger
    from backend.daemon import trigger

    assert trigger.dogfooding_ledger is ledger, (
        "trigger.py holds a different ledger object than the one conftest "
        "redirected, so its writes go somewhere unmonitored"
    )
    before = ledger.snapshot()["barge_ins"]
    trigger.dogfooding_ledger.record_barge_in()
    assert ledger.snapshot()["barge_ins"] == before + 1


if __name__ == "__main__":
    print("run via pytest (uses tmp_path)")
