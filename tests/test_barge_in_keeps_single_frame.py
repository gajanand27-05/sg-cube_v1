"""Barge-in must NOT seed its capture from the pre-roll.

Deliberate asymmetry, decided 2026-09-22. The follow-up path was given a
trimmed pre-roll to stop losing the head of the utterance (see
tests/test_followup_preroll_trim.py); barge-in keeps its single trigger frame
and accepts the same ~880ms loss.

Why the trim cannot be reused here: the follow-up trim works by keeping only
frames that START after playback ended. Barge-in is BY DEFINITION the user
talking while Onyx is still speaking, so `speech_boundary()` is +inf and every
frame fails that test anyway. There is nothing to recover by time. The head of
a barge-in capture genuinely contains both voices mixed, and there is no
acoustic echo cancellation anywhere in the tree.

What a contaminated barge-in capture costs, concretely: the stop rule is
FULLY ANCHORED —

    ^(?:stop|stop\\s+(?:it|that|talking|speaking|listening|playing.*)
       |cancel|...|abort|halt|enough|wait)$

so it is an exact match, not a prefix or a substring one. Prepending the tail
of Onyx's own sentence turns "Stop." into "...how can I help you today? Stop.",
which matches nothing, falls through to the LLM agent, and reproduces the
exact regression rule_engine.py's own comment describes: "what made 'onyx stop'
appear to be ignored, then answered aloud ten seconds later".

Losing 880ms is recoverable — the user repeats themselves. A "stop" or a "yes"
that misses the rule tier is not. This test exists so a later change that
"unifies" the two capture paths has to argue with the reasoning rather than
silently delete it. Revisit if AEC ever lands.
"""
import inspect
import math
import sys
from pathlib import Path

_root = Path(__file__).resolve().parents[1]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from backend.ai_modules.speech import tts_piper
from backend.core.orchestrator.rule_engine import RULES
from backend.daemon import wake_word as ww


def _barge_in_branch() -> str:
    src = inspect.getsource(ww.WakeWordListener.listen)
    start = src.index("if not trigger and self._check_barge_in")
    return src[start:src.index("if not trigger:", start)]


def test_barge_in_seeds_the_capture_with_the_trigger_frame_only():
    """The pin. No pre-roll on this path."""
    branch = _barge_in_branch()
    assert "initial_audio = [data]" in branch, (
        "barge-in no longer seeds from the trigger frame alone"
    )
    assert "clean_preroll" not in branch and "_preroll" not in branch, (
        "barge-in is pulling from the pre-roll — that buffer fills during "
        "playback and there is no AEC, so this injects Onyx's own voice into "
        "a capture that is by definition taken mid-sentence"
    )


def test_the_trim_would_yield_nothing_here_anyway(monkeypatch):
    """Not just policy — the boundary test is vacuous during playback.

    Barge-in happens while an utterance is open, so speech_boundary() is +inf
    and no frame can pass. Using the pre-roll here would mean bypassing the
    trim, not applying it.
    """
    monkeypatch.setattr(tts_piper, "_recent_spoken",
                        tts_piper.deque([tts_piper._Utterance(
                            text="how can I help you today?",
                            tokens=("how",),
                            started_at=tts_piper.time.monotonic())]))
    assert tts_piper.speech_boundary() == math.inf
    frames = [(1.0, b"\x00\x00"), (2.0, b"\x11\x11")]
    assert ww.clean_preroll(frames, tts_piper.speech_boundary()) == []


def test_the_stop_rule_is_an_exact_match_so_contamination_breaks_it():
    """The cost this asymmetry is buying. Measured against the real rule."""
    stop_pattern = RULES[0][0]

    assert stop_pattern.match("stop"), "fixture is pointing at the wrong rule"
    assert stop_pattern.match("cancel")

    # What a pre-roll-contaminated barge-in transcript would look like.
    for contaminated in (
        "how can I help you today? stop",
        "i've got you covered. stop",
        "sure thing. cancel",
    ):
        assert not stop_pattern.match(contaminated), (
            f"{contaminated!r} unexpectedly matched — if the stop rule ever "
            "becomes lenient, revisit the barge-in trade-off, because "
            "contamination would no longer be fatal to it"
        )


def test_a_bare_confirmation_answer_is_the_other_casualty():
    """"yes" is the shape of a confirmation answer for a DESTRUCTIVE tool.
    Contaminated, it is measured to be DROPPED by the echo gate — the failure
    mode that loses the answer entirely rather than mishearing it."""
    from backend.ai_modules.speech.tts_piper import _containment, _normalize

    spoken = _normalize("I've got you covered. How can I help you today?")
    clean = _normalize("yes")
    contaminated = _normalize("I've got you covered. How can I help you today? yes")

    assert _containment(spoken, clean) < 1.0, (
        "a bare 'yes' already looks like an echo; the premise of this test is "
        "that contamination is what pushes it over the line"
    )
    assert _containment(spoken, contaminated) > _containment(spoken, clean), (
        "contamination did not raise the echo score — re-derive the argument "
        "for keeping barge-in on a single frame"
    )


if __name__ == "__main__":
    for _name, _fn in sorted(globals().items()):
        if _name.startswith("test_") and callable(_fn):
            print(f"  [SKIP] {_name} (needs pytest)")
