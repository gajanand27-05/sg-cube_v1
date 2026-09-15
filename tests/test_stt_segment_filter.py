"""The segment quality gate must not veto short commands.

`_collect_segments` dropped any segment with no_speech_prob > 0.6. Measured
against the 30-clip real-voice corpus (36 segments, medium/cuda/fp16), that
gate fired exactly once — on "stop":

    stop_1   'Stop.'   no_speech_prob=0.616   avg_logprob=-0.644   DROPPED

Whisper transcribed the word perfectly and was confident about it. It was
discarded by 0.016 of no_speech_prob, and "stop" is the one command that must
never be silently lost — it is the barge-in / abort control.

The cause is structural, not a bad clip: one-word utterances score high
no_speech_prob regardless of how clearly they are spoken. `stop_2`
("Onyx. Stop.") survived at 0.542 only because the wake word made it longer.
So every short command is exposed, and "stop" is the shortest.

Measured distribution over those 36 real-speech segments:
    no_speech_prob   min 0.098   median 0.282   max 0.616   <- max IS stop_1
    avg_logprob      min -0.868  median -0.460  max -0.293  <- never near -1.5

And 3s of pure silence produced ZERO segments, because vad_filter=True removes
silence upstream. So no_speech_prob was never what protected against silence;
its only measurable effect on real audio was deleting "stop".

The gate now requires BOTH signals to agree before discarding.
"""
import sys
from pathlib import Path

import pytest

_root = Path(__file__).resolve().parents[1]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from backend.ai_modules.speech.stt_whisper import _collect_segments


class _Seg:
    """A faster-whisper segment, reduced to the fields the filter reads."""

    def __init__(self, text, no_speech_prob, avg_logprob):
        self.text = text
        self.no_speech_prob = no_speech_prob
        self.avg_logprob = avg_logprob


class _Info:
    language = "en"
    language_probability = 1.0
    duration = 1.0


def _collect(*segs):
    return _collect_segments(list(segs), _Info())["text"]


def test_stop_survives_the_quality_gate():
    """The regression. Real measured values from tools/_stt_corpus/stop_1.wav."""
    assert _collect(_Seg("Stop.", 0.616, -0.644)) == "Stop."


def test_short_commands_with_high_no_speech_survive_when_confident():
    """stop_1 is not a special case — every one-word command is exposed."""
    for word in ("Stop.", "Cancel.", "Mute.", "Pause."):
        assert _collect(_Seg(word, 0.72, -0.70)) == word, word


def test_a_segment_both_signals_reject_is_still_dropped():
    """The gate must still do its job: confident-sounding garbage on noise
    shows up as high no_speech AND poor logprob together."""
    assert _collect(_Seg("mmm hmm okay so", 0.85, -1.2)) == ""


def test_incoherent_output_is_dropped_on_logprob_alone():
    """Unchanged behaviour — avg_logprob < -1.5 still vetoes by itself, even
    when no_speech_prob looks fine."""
    assert _collect(_Seg("the the the the", 0.10, -1.8)) == ""


def test_the_no_speech_threshold_cannot_veto_alone():
    """Guard on the rule itself. Reverting to `no_speech_prob > 0.6` as an
    independent veto silently re-breaks "stop", and the symptom downstream is
    an empty transcript — indistinguishable from the user not speaking.
    """
    very_high_no_speech_but_confident = _Seg("Stop.", 0.99, -0.5)
    assert _collect(very_high_no_speech_but_confident) == "Stop."


def test_real_speech_logprob_range_stays_inside_the_hard_veto():
    """The -1.5 hard veto had margin when measured: the worst real-speech
    segment in the corpus was -0.868. Pin that the veto sits below the
    measured floor, so tightening it later is a deliberate act.
    """
    worst_measured_real_speech = -0.868
    assert _collect(_Seg("summarize this page", 0.3, worst_measured_real_speech)) != ""
