"""Two overlapping turns must not both produce audio.

Reported live: "I'm hearing double voice — it's processing two tasks one after
the other and producing two outputs at once."

The log that goes with it:

    [wake] previous turn still running after 15s; starting anyway
    [wake] previous turn still running after 15s; starting anyway
    [command] "I'll see you tomorrow."
    [ai] response: It sounds like you're thinking out loud... (latency: 27032ms)
    [ai] response: Sounds good! I'll be here whenever you need me. (latency: 6408ms)

Two `[ai] response` lines back to back with no interrupt between them: two turn
bodies reached the speak stage.

`test_turn_queue_ownership.py` already covers why overlap does not CRASH — each
turn owns its SentenceQueue. What it does not cover is that the superseded turn
keeps talking. `new_sentence_queue()` hands the `_CURRENT` pointer to the new
turn and, by its own docstring, leaves the previous queue alone "still draining
on its own loop". That draining consumer keeps pulling sentences and calling
speak_stream, so:

  * Sentences interleave. tts_piper._activate is "newest wins" per SENTENCE,
    not per turn, so turn A's next sentence stops turn B's current one, which
    stops A's next, and the user hears two answers chopped together.
  * They genuinely overlap in time. _activate only sets the previous session's
    stop Event; it does not close the device. `_audio_player` is blocked inside
    a blocking `stream.write()` and cannot observe that Event until the write
    returns, so a second sd.OutputStream opens while the first is still
    feeding the device. Two streams open = the mixer plays both.

The handover timeout is not the thing to fix. It is a deliberate safety valve
(a wedged turn must not deafen the listener forever), so overlap stays
reachable by design and the speaking side has to be correct under it.

Fix belongs in `new_sentence_queue()`: taking over `_CURRENT` is exactly the
moment the outgoing turn stops being the turn that speaks.
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


def test_superseded_turn_stops_speaking():
    """The regression, stated directly and without threads.

    Turn A is mid-turn — queue built, consumer running — when turn B takes
    over. Everything A tries to say from that moment on belongs to an answer
    the user has already been given a newer response to.
    """
    spoken = []

    async def body():
        a = tts_queue.new_sentence_queue()
        await a.start()
        await a.enqueue("A sentence one.")

        # Turn B starts while A is still live. This is the handover.
        b = tts_queue.new_sentence_queue()
        await b.start()

        # A's brain is still streaming sentences at this point — that is the
        # whole reason it is still alive — so it keeps enqueuing.
        await a.enqueue("A sentence two.")
        await b.enqueue("B sentence one.")

        await a.finish()
        await b.finish()

    with patch.object(tts_queue, "speak_stream", _fake_speak_stream(spoken)):
        asyncio.run(body())

    assert "A sentence two." not in spoken, (
        f"superseded turn kept speaking after handover: {spoken!r} — turn A "
        "enqueued after turn B became current, so the user hears both answers "
        "at once"
    )
    assert "B sentence one." in spoken, (
        f"the new turn went silent: {spoken!r} — the handover must interrupt "
        "the OLD turn, never the incoming one"
    )


def test_handover_interrupts_the_outgoing_queue():
    """Same defect at the state level, with no event loop involved.

    Stated separately because the symptom the user hears is audio, but the
    thing that has to be true is that the outgoing queue is marked interrupted
    the moment it stops being current.
    """
    outgoing = tts_queue.new_sentence_queue()
    incoming = tts_queue.new_sentence_queue()

    assert outgoing._interrupted, (
        "handing _CURRENT to a new turn left the previous queue live; its "
        "consumer keeps draining and calling speak_stream"
    )
    assert not incoming._interrupted, "the incoming turn must not interrupt itself"


def test_first_turn_of_a_session_is_not_interrupted():
    """There is no outgoing turn to stop when nothing has run yet, and
    interrupting the only queue would mute the first thing Onyx ever says."""
    tts_queue._CURRENT = None
    first = tts_queue.new_sentence_queue()
    assert not first._interrupted, "the first turn of the session was muted"


if __name__ == "__main__":
    for _name, _fn in sorted(globals().items()):
        if _name.startswith("test_") and callable(_fn):
            _fn()
            print(f"  [PASS] {_name}")
