"""A turn must own its sentence queue, not borrow a shared one.

`test_turn_serialization.py` covers the first half of this defect: turn bodies
are serialized so two of them do not normally run at once. But that serializing
is *bounded* — `_TURN_HANDOVER_TIMEOUT_S` (15s) exists so a wedged turn cannot
deafen the listener forever, and when it expires `_start_turn` prints
"previous turn still running; starting anyway" and proceeds. At that moment two
turn bodies are live, each on its own `asyncio.run()` loop, and the original
failure is back:

    [ai] Brain error: Task <... _handle_wake_async()> got Future
         <Task ... SentenceQueue._consumer()> attached to a different loop
    [ai] -> Sorry, I encountered an error

Root cause is not the overlap; it is that `SentenceQueue` was a module-level
singleton whose `start()` rebinds `_queue` and `_task` to the *calling* loop.
Turn N+1's start() overwrote the task turn N was still awaiting in `finish()`.
Serializing merely made that rare.

So ownership moves: each turn gets its own SentenceQueue via
`new_sentence_queue()`, and the module only remembers which one is *current* so
that barge-in / wake / "stop" can interrupt the active turn from another
thread. Same shape as `tts_piper._PlaybackSession` (T-tts-loop-globals), which
fixed the identical hazard on the playback side.
"""
import asyncio
import sys
import threading
from pathlib import Path
from unittest.mock import patch

_project_root = Path(__file__).resolve().parents[1]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from backend.ai_modules.speech import tts_queue


def _fake_speak_stream(recorder):
    async def _speak(text):
        recorder.append(text)
        yield b""
    return _speak


def test_overlapping_turns_do_not_share_a_queue():
    """The regression. Two turn bodies on two loops, sequenced so the second
    starts while the first is still mid-turn — exactly what the handover
    timeout permits. Neither may die with a cross-loop error."""
    spoken = []
    errors = {}
    a_started = threading.Event()
    b_started = threading.Event()
    a_done = threading.Event()

    def turn(name, before_finish):
        async def body():
            sq = tts_queue.new_sentence_queue()
            await sq.start()
            before_finish()
            await sq.enqueue(f"{name} speaking.")
            await sq.finish()

        try:
            asyncio.run(body())
        except BaseException as e:          # noqa: BLE001 - recording it IS the test
            errors[name] = f"{type(e).__name__}: {e}"

    def a_gate():
        a_started.set()
        # Do not finish until turn B has taken over the module state.
        b_started.wait(5)

    def b_gate():
        b_started.set()
        # B must still be MID-turn — consumer task pending — while A finishes.
        # Awaiting an already-completed foreign task is legal, so a version of
        # this test that let B finish first passed against the broken code.
        a_done.wait(5)

    with patch.object(tts_queue, "speak_stream", _fake_speak_stream(spoken)):
        ta = threading.Thread(target=turn, args=("A", a_gate), daemon=True)
        ta.start()
        assert a_started.wait(5), "turn A never started"
        tb = threading.Thread(target=turn, args=("B", b_gate), daemon=True)
        tb.start()
        ta.join(10)
        a_done.set()
        tb.join(10)

    assert not errors, (
        f"overlapping turns raised {errors} — a turn is still awaiting state "
        "that another turn's loop owns"
    )
    # This used to assert sorted(spoken) == ["A speaking.", "B speaking."].
    # That was written as a liveness check — "both turns got through their body
    # without dying" — but what it actually pinned was the double-voice bug:
    # A enqueues AFTER B has taken over, and asserting A still speaks requires
    # the superseded turn to keep talking over the new one. Reported live as
    # "I'm hearing double voice". See test_no_double_voice_across_turns.py.
    #
    # The liveness this test wants is "A completed its body", which `errors`
    # already proves. B is the current turn, so B is the one that must be
    # audible.
    assert "B speaking." in spoken, f"the current turn went silent: {spoken!r}"


def test_each_turn_gets_a_distinct_queue():
    """Ownership, stated directly: two turns must not be handed the same
    object, or turn N+1's start() resets turn N's `_spoke_anything` and
    rebinds the task turn N is awaiting."""
    first = tts_queue.new_sentence_queue()
    second = tts_queue.new_sentence_queue()
    assert first is not second, (
        "both turns got the same SentenceQueue; start() would rebind the "
        "loop-bound queue and consumer task out from under the earlier turn"
    )


def test_interrupt_reaches_the_current_turn():
    """The reason a module-level pointer survives at all: barge-in, wake and
    'stop' all call get_sentence_queue().interrupt() from the LISTENER thread,
    and it has to land on the turn that is actually speaking."""
    stale = tts_queue.new_sentence_queue()
    live = tts_queue.new_sentence_queue()

    tts_queue.get_sentence_queue().interrupt()

    assert live._interrupted, "interrupt() missed the current turn"
    # `stale` is now interrupted too, but by the HANDOVER rather than by this
    # call — building `live` is what silenced it, which is the double-voice
    # fix. So the old `assert not stale._interrupted` no longer states
    # anything about where interrupt() landed.
    #
    # What this test is actually for is that the pointer tracks the newest
    # turn, so assert that directly instead of inferring it from a flag that
    # two different things can now set.
    assert tts_queue.get_sentence_queue() is live, (
        "the current-turn pointer is not the newest turn built; barge-in, wake "
        "and 'stop' would all land on a turn that is no longer speaking"
    )


def test_depth_reads_the_current_turn_without_building_one():
    """Reading a metric must not construct the thing it measures — otherwise
    /diagnostics quietly installs a queue that no turn owns."""
    tts_queue._CURRENT = None
    assert tts_queue.sentence_queue_depth() is None
    assert tts_queue._CURRENT is None, "reading depth built a queue"

    q = tts_queue.new_sentence_queue()
    assert tts_queue.sentence_queue_depth() == q.depth


if __name__ == "__main__":
    for _name, _fn in sorted(globals().items()):
        if _name.startswith("test_") and callable(_fn):
            _fn()
            print(f"  [PASS] {_name}")
