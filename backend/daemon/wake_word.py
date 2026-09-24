import json
import queue
import threading
import time
from collections import deque
from typing import Any, Callable, Optional, Generator

from backend.core import paths

import numpy as np
import sounddevice as sd
import vosk

from backend.ai_modules.speech.tts_piper import is_speaking
from backend.core.agents.pending_confirmation import store as _pending_store
from backend.core.events import get_bus, Priority
from backend.daemon.ui_events import FollowUpExpired
from backend.core.dogfooding import ledger as dogfooding_ledger
from backend.core.state import AssistantState, manager as state_manager
from backend.server.config import settings

vosk.SetLogLevel(-1)

MODELS_DIR = paths.VOSK_DIR
DEFAULT_MODEL = "vosk-model-small-en-us-0.15"

# VAD tuning for command capture. RMS values are int16-amplitude scaled
# (full-scale = 32768). 400 is well above mic noise floor on consumer
# laptops but below normal speech (~1500-3000).
# DO NOT RAISE THIS. It looks too low — a live wake fired at rms=55 and the
# capture behind it measured rms=15, i.e. Vosk was handed near-silence and
# decoded '[unk] onyx' from it. Raising it makes that worse, not better:
#
# This gate decides which frames reach the recognizer at all, so raising it
# DROPS the quiet gaps between words and splices the loud fragments into a
# discontinuous stream. Vosk then hallucinates the wake phrase out of ordinary
# speech. Measured against tests/test_barge_in_real_audio.py, which drives the
# real loop and the real model with a clip verified NOT to contain "onyx":
#
#     threshold  50 -> 4 passed
#     threshold  70 -> 1 failed   (false wake on plain speech, rms 5296)
#     threshold  90 -> 1 failed
#     threshold 120 -> 1 failed
#
# So 50 is load-bearing, not a leftover. The rms=55 nuisance wake is already
# handled downstream: capture rejects it ("skipping whisper: capture too
# quiet") and it counts toward the empty-capture close. Trading a handled
# nuisance for false wakes on real speech is a bad deal.
# Now settings-driven (VAD_RMS_THRESHOLD in .env), defaulting to the measured
# 50 below. Everything in the comment above still holds — this is a knob for
# rooms whose noise floor makes 50 unusable, not an invitation to raise it.
# Measure with tools/calibrate_mic.py; do not guess.
_VAD_RMS_THRESHOLD = settings.vad_rms_threshold

# The "has the user STOPPED talking" gate. Separate from _VAD_RMS_THRESHOLD
# because the two want opposite things:
#
#   _VAD_RMS_THRESHOLD        must stay LOW  — it decides which frames reach
#                             the Vosk recognizer, and raising it splices
#                             loud fragments together until Vosk hallucinates
#                             the wake phrase (see the comment above it).
#   _CAPTURE_SILENCE_THRESHOLD must sit ABOVE the room floor — it decides when
#                             800ms of trailing silence has accumulated.
#
# Measured in a real room (Voice Clarity on, two people talking 2m away):
# floor p50 384 / p90 1161, speech p25 4753. At a shared threshold of 50,
# ZERO frames of 30s of silence fell below the gate, so trailing silence never
# accumulated and every capture ran to the 10s hard cap. Raising the shared
# constant was not available — test_barge_in_real_audio fails at 100+.
#
# Defaults to _VAD_RMS_THRESHOLD, so this changes nothing until calibrated
# with tools/calibrate_mic.py.
_CAPTURE_SILENCE_THRESHOLD = settings.capture_silence_threshold
_VAD_TRAILING_SILENCE_MS = 800  # stop after this much silence post-speech
_VAD_MAX_CAPTURE_S = 10.0  # hard cap so a stuck mic doesn't hang forever
_VAD_INITIAL_WAIT_S = 3.0  # how long to wait for the user to start speaking

# Follow-up is content-gated: it closes on ABSENCE of usable speech, not on a
# stopwatch from the moment the assistant stopped talking.
#
# The old flat 3.0s deadline was shorter than a person takes to hear a
# sentence, decide, and start speaking, so nearly every exchange needed the
# wake word again — a command line with extra steps rather than a
# conversation.
#
# Idle is the think-time budget; a failed attempt buys a fresh one (you
# mumbled, you get another go, not the 400ms left on the old clock).
_FOLLOWUP_IDLE_S = 8.0
# The brake, and the reason this is safe to widen at all. Under the restricted
# grammar we can tell that speech HAPPENED but not that it was addressed to
# us (T-wake-word-executes-ambient-audio), so an unbounded chain of refreshes
# would let a television drive the assistant. No chain outlives this without a
# fresh wake word.
_FOLLOWUP_MAX_S = 45.0
_FOLLOWUP_MAX_EMPTY = 2

# Loudness floor for a follow-up trigger. The window fires on decoded content
# rather than volume, which is right — but with no floor at all, room noise
# decoding to "[unk]" started full turns. Measured false triggers in one live
# session: rms 64, 106, 178, 197, 203, all capturing nothing. Real follow-up
# speech in the same session: 975, 1288, 1769, 2908.
#
# Below barge_in_rms_threshold (800) on purpose: a follow-up is someone
# talking to a SILENT assistant and should not need the volume of talking
# over one.
_FOLLOWUP_MIN_RMS = 400

# How long a new turn waits for the previous one to unwind before starting
# anyway. Generous: the previous turn has already been interrupted, so this is
# a safety valve against a wedged turn, not a normal wait.
_TURN_HANDOVER_TIMEOUT_S = 15.0

# Frames of mic audio kept behind the live position, so the head of a command
# survives wake recognition.
#
# The listen loop feeds every frame to Vosk and then drops it; _capture() picks
# up at the queue's CURRENT position, so whatever was spoken while the
# recognizer was still accumulating evidence for "onyx" is simply gone.
# Measured against the real model on a real recording of this user, varying the
# wake word's alignment against the 125ms block grid:
#
#     lag: min 125ms, median 500ms, max 1625ms   (n=8)
#
# Half a second of the command, routinely. That is the whole first word, and it
# matches the reported mis-transcriptions exactly:
#     "can you hear me" -> 'Hear me on X.'      ("can you" lost)
#     "close notepad"   -> 'This is notepad.'   ("close" lost)
#
# Sized to the measured maximum: 13 frames x 125ms = 1625ms, about 52KB.
# Erring long is cheap (the extra audio is the wake word and the quiet before
# it, which Whisper handles); erring short loses the first word.
_PREROLL_FRAMES = 13


def _has_followup_content(partial: str) -> bool:
    """Legacy word-shape gate. DO NOT use against this listener's partials.

    Kept because it is still the right check for a free-vocabulary
    recognizer, but ours is grammar-restricted to [wake_phrase, "[unk]"]:
    every out-of-vocabulary word — i.e. everything the user actually says
    after the wake phrase — comes back as the literal token "[unk]", which
    has no alphabetic characters. Measured against the real model, this
    returned False for every frame of two recorded speech clips and True
    only on the frames containing "onyx". Gating anything on it means
    gating on "did they say the wake word again". Use `_partial_grew`.
    """
    return any(len(w) >= 2 and w.isalpha() for w in partial.split())


# 2000 samples = 125ms at 16kHz — the live stream's blocksize, and the cadence
# PartialResult updates at. Exported so an offline replay feeds Vosk in exactly
# the sized bites the microphone does; chunk size changes where token
# boundaries fall, so a bench using a different one measures a different
# recognizer.
WAKE_BLOCKSIZE = 2000


def feed_wake_chunk(recognizer, data: bytes) -> str:
    """Feed ONE chunk to the wake recognizer; return its cumulative partial.

    Extracted so the live listener and tools/wake_bench.py run the SAME
    decision. A bench that re-implements this measures the re-implementation —
    which is worthless for a before/after comparison, since the thing being
    compared is production behaviour.

    The caller owns the RMS gate (_VAD_RMS_THRESHOLD) and Reset(), because
    both are part of the surrounding state machine rather than this step.
    """
    recognizer.AcceptWaveform(data)
    return (json.loads(recognizer.PartialResult()).get("partial") or "").lower()


def _speak_cue(text: str) -> None:
    """Say one short line through the existing TTS path.

    Module-level rather than a method so tests can replace it without a
    speaker, and so the import stays lazy — wake_word is imported by tooling
    that has no audio device.

    Uses tts_piper.speak (the blocking wrapper) because the caller is already
    on the wake worker thread with no running loop, which is the same reason
    the turn body itself uses asyncio.run.
    """
    from backend.ai_modules.speech.tts_piper import speak

    speak(text)


def clean_preroll(frames, boundary: float) -> list[bytes]:
    """Pre-roll frames that cannot contain Onyx's own speech.

    `frames` is (frame_start_monotonic, pcm) as stamped by _cb; `boundary` is
    tts_piper.speech_boundary(). Comparing STARTS is what makes a frame
    straddling the end of playback drop rather than survive: its first samples
    are still our voice however late it finishes.

    Pure and total — the infinities in speech_boundary() mean there is no
    "still speaking" or "never spoke" branch to get wrong here.
    """
    return [data for start, data in frames if start > boundary]


def wake_phrase_present(partial: str, wake_phrase: str) -> bool:
    """The live trigger test: a bare token match, with no confidence check.

    Vosk's grammar here is [wake_phrase, "[unk]"], so every sound must decode
    to one or the other — which is structurally prone to accepting ambient
    speech as the wake word.
    """
    return wake_phrase in partial.split()


def _partial_token_count(partial: str) -> int:
    """Tokens Vosk has decoded so far in the current utterance."""
    return len(partial.split())


def _partial_grew(partial: str, previous_tokens: int) -> bool:
    """True when Vosk decoded NEW audio-as-speech on this frame.

    Two measured properties of the real recognizer drive this:

      1. Loud non-speech does not decode at all. A click train at 3085 RMS
         and a 220Hz tone at 5656 RMS — both far above the 800 barge-in
         threshold and above the 2854 RMS room transients that were
         self-interrupting playback — produce an empty partial and an empty
         FinalResult. The acoustic model rejects them. This is the signal
         that separates a door slam from a person.
      2. PartialResult is CUMULATIVE. It keeps returning the whole
         accumulated string on subsequent silent frames, so "is the partial
         non-empty" latches True after the first utterance and never
         un-latches until Reset(). Only an INCREASE in the token count is
         per-frame evidence; the count is the gate, not the text.
    """
    return _partial_token_count(partial) > previous_tokens



class WakeWordListener:
    """Continuously samples the mic and fires `on_wake(captured_audio_bytes)`
    when `wake_phrase` is recognised.

    Two callbacks:
      - on_wake_detected(): fires the instant the wake phrase is recognised,
        BEFORE any audio is captured. Use it to flash the UI and play a
        chime so the user gets immediate feedback.
      - on_wake(audio_bytes): fires after the command audio has been
        captured (variable length, VAD-controlled).

    Capture length is no longer fixed: we read chunks from the mic, look
    for ~700ms of silence following speech, and stop. Hard caps at 8s.
    """

    # Class-level defaults for the follow-up clocks. __init__ sets both, but
    # several tests build a listener with object.__new__ to avoid loading a
    # Vosk model, and _followup_open() reads BOTH. Without these, such a
    # listener raises AttributeError inside the listen thread the moment the
    # window is open — and `and` short-circuits, so a closed window hides it
    # entirely. That is a crash that only appears once the feature is working.
    _followup_until: float = 0.0
    _followup_hard_until: float = 0.0
    _empty_in_a_row: int = 0
    # Same reason: _cb reads it to stamp every frame, and the tests that feed
    # frames through _cb build the listener with object.__new__. The real
    # value is set in __init__ and refined in listen() from the open stream.
    _frame_lead_s: float = WAKE_BLOCKSIZE / 16000.0

    def __init__(
        self,
        on_wake: Callable[[bytes], Any],
        on_wake_detected: Optional[Callable[[], None]] = None,
        on_barge_in: Optional[Callable[[float], None]] = None,
        wake_phrase: str = "onyx",
        capture_seconds: float = 2.5,  # legacy arg, ignored by VAD path
        sample_rate: int = 16000,
        device: Optional[int] = None,
        model_name: str = DEFAULT_MODEL,
    ):
        model_path = MODELS_DIR / model_name
        if not model_path.exists():
            raise RuntimeError(
                f"Vosk model not found at {model_path}. "
                f"Run: python tools/download_vosk_model.py"
            )

        self.model = vosk.Model(str(model_path))
        self.recognizer = vosk.KaldiRecognizer(
            self.model, sample_rate, json.dumps([wake_phrase, "[unk]"])
        )
        self.wake_phrase = wake_phrase.lower()
        self.on_wake = on_wake
        self.on_wake_detected = on_wake_detected
        self.on_barge_in = on_barge_in
        self.capture_seconds = capture_seconds  # unused; kept for arg compat
        self.sample_rate = sample_rate
        self.device = device
        self.queue: queue.Queue = queue.Queue()
        self._running = False
        self._capturing = False
        # How far before the callback a frame's audio actually STARTED.
        # Provisional: one blocksize. listen() adds the stream's reported
        # input latency once the device exists. See _cb.
        self._frame_lead_s = WAKE_BLOCKSIZE / float(sample_rate)
        # Phase 4A: consecutive high-RMS chunks while state == SPEAKING;
        # resets to 0 on any low-RMS chunk. When it reaches
        # settings.barge_in_debounce_frames, we fire barge-in.
        self._barge_in_frames = 0
        # Token count of the last partial we saw, so a frame can be judged
        # as "Vosk decoded something new" rather than "the mic was loud".
        self._partial_tokens = 0
        # Sticky within one debounce run: did ANY frame of this run carry new
        # decoded speech? Vosk emits a token every few frames, not every
        # frame, so requiring growth on all N would never pass.
        self._barge_in_saw_speech = False
        # Follow-up bookkeeping. Instance state rather than locals in listen()
        # because the turn now finishes on a worker thread, which is what
        # decides whether the window opens.
        self._followup_until: float = 0.0   # monotonic; <= now == closed
        # Ceiling for one wake-free chain; see _FOLLOWUP_MAX_S.
        self._followup_hard_until: float = 0.0
        self._empty_in_a_row: int = 0
        self._turn_thread: Optional[threading.Thread] = None
        # Rolling window of recent frames — see _PREROLL_FRAMES.
        self._preroll: deque[bytes] = deque(maxlen=_PREROLL_FRAMES)

    # ── follow-up window ──────────────────────────────────────────────────
    # Kept as three small methods rather than inline arithmetic in listen()
    # so the close conditions are testable without driving a mic, a model and
    # a thread to observe them.

    def _wake_trigger_allowed(self, rms: float) -> bool:
        """May a decoded wake phrase start a turn at this loudness?

        Not while we are SPEAKING, unless it is loud enough to be a real
        interruption. Barge-in is guarded by an RMS floor and a debounce; the
        bare wake test beside it had neither, so our own TTS bleeding back
        into the mic decoded as "onyx" and started a turn at rms=54 — cutting
        off the sentence still being spoken, capturing nothing, and repeating.
        Every barge-in protection was bypassed by sitting in the other branch.

        Deferring to the same threshold keeps one number in charge of "is this
        the user talking over us". With barge-in disabled there is no other
        way to interrupt, so the guard steps aside.

        "Are we speaking?" is asked of the TTS module as well as the state
        machine, because the state machine can be stale in exactly the
        situation that matters. Two turns overlap, turn A is mid-reply, turn B
        finishes and runs its own transition_to(IDLE) — and from then on A's
        playback is unguarded. That is what these are:

            [wake] heard wake: 'onyx' (rms=88)      [TTS] Speech interrupted
            [wake] heard wake: 'onyx' (rms=73)      [TTS] Speech interrupted
            [wake] heard wake: '[unk] onyx' (rms=59)[TTS] Speech interrupted

        wakes far below any speech level, each cutting a live sentence. Note
        the fix is NOT an RMS floor on the wake path: while nothing is
        playing, a quiet "onyx" is a wake we want, and _VAD_RMS_THRESHOLD is
        load-bearing at 50. is_speaking() answers the question exactly —
        it reports whether the current playback session's player task is
        still running.
        """
        if not settings.enable_barge_in:
            return True
        try:
            playing = is_speaking()
        except Exception:
            playing = False
        if state_manager.current != AssistantState.SPEAKING and not playing:
            return True
        return rms >= settings.barge_in_rms_threshold

    def _followup_trigger_allowed(self, rms: float) -> bool:
        """May decoded content inside the follow-up window start a turn?

        The window fires on Vosk token growth with no loudness floor at all.
        That part is deliberate — near-silence must never qualify, and a
        loudness-only rule is what let ambient audio run whole commands. But
        with no floor, room noise decoding to "[unk]" starts a full turn:
        measured firing at rms=64, 106, 178, 197 and 203, every one of them
        capturing nothing.

        Lower than the barge-in floor on purpose: a follow-up is someone
        talking to a SILENT assistant, which does not need the volume of
        talking over one.
        """
        return rms >= _FOLLOWUP_MIN_RMS

    def _followup_trigger(self, rms: float) -> bool:
        """The gate decision, plus a count of what it turned away.

        Identical behaviour to `_followup_trigger_allowed` — this only adds
        the tally, so the rejections are visible as numbers rather than as an
        absence. Without them the archive can show what RAISING the floor
        would cost and nothing about what 400 already drops, and the sample is
        censored at exactly that point.

        Recording only: the threshold moves when there is archived evidence to
        move it with, not tonight.
        """
        if self._followup_trigger_allowed(rms):
            return True
        try:
            from backend.core import capture_archive

            capture_archive.record_gate_rejection(rms, floor=_FOLLOWUP_MIN_RMS)
        except Exception:
            pass
        return False

    def _open_followup(self, window: float | None = None, *,
                       new_chain: bool = False) -> None:
        """Open (or refresh) the window and reset the failure count.

        `window` overrides the idle budget — the confirmation path passes a
        longer one, because hearing a question and deciding takes longer than
        continuing a thought.

        `new_chain` must be True ONLY when a wake word (or barge-in) started
        this exchange. It is what restarts the ceiling clock, so it is the
        single point where the ambient-audio brake can be released. Defaulting
        it to False is deliberate: a refresh that silently restarted the
        ceiling would make _FOLLOWUP_MAX_S unreachable and the brake
        decorative.
        """
        now = time.monotonic()
        if window is None:
            window = _FOLLOWUP_IDLE_S
        if new_chain or self._followup_hard_until <= 0.0:
            self._followup_hard_until = now + _FOLLOWUP_MAX_S
        self._followup_until = min(now + window, self._followup_hard_until)
        self._empty_in_a_row = 0

    def _question_pending(self) -> bool:
        """Is Onyx owed an answer — of either kind?

        A yes/no confirmation, or a half-built call waiting on a missing
        argument. The second is the one that cost a WhatsApp message: it was
        not represented anywhere, so nothing could ask this question about it.
        """
        from backend.core.agents.pending_clarification import (
            store as _clarification_store,
        )

        try:
            return bool(_pending_store.awaiting_answer()
                        or _clarification_store.awaiting_answer())
        except Exception:
            return False

    def _announce_followup(self, window: float) -> None:
        """Tell the user where the chain stands, on every channel that fits.

        Three audiences, three costs:
          * the log — always;
          * a UI event — on every expiry. Silent, and the HUD had no way to
            know the window had shut;
          * SPEECH — only when the chain is dead AND an answer is owed.

        The speech condition is the whole design. Announcing every expiry
        would append a sentence to the end of every exchange and train the
        user to talk over Onyx, which is the behaviour this is meant to
        prevent. A dead chain with nothing outstanding is unremarkable; a dead
        chain with a question on the table is the bug from the log.

        Deliberately not _play_chime(): that chime means "I am listening", so
        reusing it to announce the opposite is worse than silence.
        """
        print(self._followup_notice(window))
        if self._followup_open():
            return

        owed = self._question_pending()
        # Never let a notice kill the turn thread. This runs on the wake
        # worker, and an exception here would look like a dead assistant.
        try:
            get_bus().publish(
                FollowUpExpired(question_pending=owed,
                                wake_phrase=self.wake_phrase),
                priority=Priority.NORMAL,
            )
        except Exception as e:
            print(f"[wake] could not publish FollowUpExpired: {e}")

        if not owed:
            return
        try:
            _speak_cue(f"Say {self.wake_phrase} to answer.")
        except Exception as e:
            print(f"[wake] could not speak the expiry cue: {e}")

    def _followup_notice(self, window: float) -> str:
        """What to tell the user after a handled turn.

        Asks `_followup_open()` rather than assuming. `_open_followup` clamps
        the idle window to the hard ceiling, and an EXPIRED ceiling is still a
        positive timestamp — so the `new_chain=False` reset is skipped and the
        window opens ALREADY CLOSED. Live, after Onyx asked a question:

            [ai] response: What would you like the message to say?
            [wake] listening — 8s idle, -1s left in this chain

        The microphone was shut. The user answered into it anyway, and the
        answer only landed because Vosk hallucinated the wake word — which
        started a fresh chain that knew nothing about the pending question.

        The ceiling itself is correct and deliberately untouched: it is the
        brake against ambient audio driving the assistant. Only the claim was
        wrong.
        """
        if not self._followup_open():
            return (f"[wake] chain expired — say {self.wake_phrase!r} "
                    f"to keep going")
        remaining = self._followup_hard_until - time.monotonic()
        return (f"[wake] listening — {window:.0f}s idle, "
                f"{remaining:.0f}s left in this chain")

    def _note_empty_capture(self) -> None:
        """A capture produced nothing usable.

        Refresh rather than let the remaining milliseconds run out — but count
        it, because repeated nothing is what ambient noise looks like.
        """
        self._empty_in_a_row += 1
        if self._empty_in_a_row >= _FOLLOWUP_MAX_EMPTY:
            self._close_followup()
            return
        now = time.monotonic()
        self._followup_until = min(now + _FOLLOWUP_IDLE_S, self._followup_hard_until)

    def _close_followup(self) -> None:
        self._followup_until = 0.0
        self._followup_hard_until = 0.0
        self._empty_in_a_row = 0

    def _followup_open(self) -> bool:
        now = time.monotonic()
        return now < self._followup_until and now < self._followup_hard_until

    def _cb(self, indata, _frames, _time, _status):
        # Stamp the frame's START, here in the callback.
        #
        # Stamping at dequeue would mark the END of the frame's 125ms plus
        # however long it sat in the queue, so a frame that looks safely after
        # `ended_at` could still begin inside the TTS tail — which is exactly
        # the frame the trim exists to drop.
        #
        # PortAudio hands the callback an `inputBufferAdcTime` that would be
        # this value exactly. Measured on this machine it is ZERO on every
        # callback (MME host API reports no timing), so it is derived instead:
        # the buffer covers blocksize/samplerate of audio and was captured
        # `latency` ago. Both are reported values, not a tuned constant.
        #
        # Error direction is deliberate: subtracting the latency biases the
        # start EARLIER, so `start > boundary` gets harder to satisfy and the
        # mistake is always "dropped a clean frame", never "kept a dirty one".
        self.queue.put((time.monotonic() - self._frame_lead_s, bytes(indata)))

    def _check_barge_in(self, rms: float, partial: str = "") -> bool:
        """Return True iff, during SPEAKING, loud audio that Vosk actually
        decoded as speech passed the debounce.

        `partial` is the recognizer's cumulative PartialResult for the frame.
        Loudness alone used to be the whole gate, and room-noise transients
        measured at 2854 RMS against an 800 threshold self-interrupted
        playback. Non-speech does not decode (see `_partial_grew`), so we
        additionally require that at least one frame of the debounce run
        added a token. `settings.barge_in_require_speech = False` restores
        the old loudness-only behaviour.

        Kept as a separate method so tests can drive the sequence directly
        without needing a running mic stream. Side effects: mutates
        `_barge_in_frames`, `_barge_in_saw_speech`, `_partial_tokens`.
        """
        grew = _partial_grew(partial, self._partial_tokens)
        self._partial_tokens = _partial_token_count(partial)

        if (
            not settings.enable_barge_in
            or state_manager.current != AssistantState.SPEAKING
        ):
            # Outside SPEAKING or disabled — always reset so partial debounce
            # doesn't leak across a state transition.
            self._barge_in_frames = 0
            self._barge_in_saw_speech = False
            return False
        if rms > settings.barge_in_rms_threshold:
            self._barge_in_frames += 1
            self._barge_in_saw_speech = self._barge_in_saw_speech or grew
            speech_ok = self._barge_in_saw_speech or not settings.barge_in_require_speech
            if self._barge_in_frames >= settings.barge_in_debounce_frames and speech_ok:
                self._barge_in_frames = 0
                self._barge_in_saw_speech = False
                return True
            return False
        # RMS below threshold — reset debounce.
        self._barge_in_frames = 0
        self._barge_in_saw_speech = False
        return False

    def _start_turn(self, audio: bytes, *, new_chain: bool = True,
                    source: str = "wake", rms: float | None = None) -> None:
        """Run the turn off the listen loop.

        `new_chain` is False when this turn was triggered from inside an open
        follow-up window, so the ceiling clock keeps running instead of being
        restarted by the exchange it is supposed to bound.

        `on_wake` is handle_wake, which runs the whole turn synchronously —
        and `_run_brain_streaming` ends in `await sq.finish()`, which drains
        the sentence queue, so it does not return until the last word has been
        SPOKEN. Calling it inline meant `_capturing` stayed set for the entire
        reply and every mic frame hit the `continue` at the top of the loop.
        The listener was deaf for exactly the window in which barge-in, the
        wake word and "stop" all need to work. `[TTS] Speech interrupted`
        still appeared in the log because on_wake_detected calls stop_speech()
        unconditionally, which prints whether or not anything was playing —
        that is what made interruption look like it worked.

        Turn BODIES are serialized; the listen loop is not. That distinction
        is the whole design: the loop must keep reading the mic (or barge-in
        and "stop" are unreachable), but two turns must never execute at once.

        An earlier version of this let them overlap, on the reasoning that
        "playback state is per-call, see T-tts-loop-globals". That was true of
        tts_piper._PlaybackSession and FALSE of SentenceQueue, which is still
        a module-level singleton: start() binds a fresh queue AND a consumer
        task to the calling loop, and handle_wake runs asyncio.run() per
        capture — so a second turn on a second thread overwrote `_task` while
        the first was still awaiting it. Live result:

            got Future <Task ... SentenceQueue._consumer()> attached to a
            different loop
            -> "Sorry, I encountered an error"

        plus "await wasn't used with future" and GeneratorExit noise on
        shutdown. Roughly one turn in four died that way.

        The join happens INSIDE the new worker, never on the listen loop — a
        join there would restore exactly the deafness this method exists to
        remove. The wait is short in practice because a new trigger has
        already run on_barge_in / on_wake_detected, which stop speech and
        interrupt the commander, so the previous turn is already unwinding.
        """
        previous = self._turn_thread

        def _run() -> None:
            # Let the previous turn finish before touching any of the
            # singletons it owns. Bounded so a wedged turn cannot deafen us
            # forever; if it does time out we proceed and accept the risk,
            # because silently dropping the user's command is worse.
            if previous is not None and previous.is_alive():
                previous.join(timeout=_TURN_HANDOVER_TIMEOUT_S)
                if previous.is_alive():
                    print(f"[wake] previous turn still running after "
                          f"{_TURN_HANDOVER_TIMEOUT_S:.0f}s; starting anyway")

            # Hand the listener's own measurement to whoever archives this
            # capture. Set HERE, on the turn's thread, so it cannot be
            # overwritten by an overlapping turn — see the note in
            # capture_archive.set_trigger_context for why this is not a module
            # global and not an on_wake argument.
            if rms is not None:
                try:
                    from backend.core import capture_archive

                    capture_archive.set_trigger_context(
                        rms=round(float(rms), 1),
                        followup_min_rms=_FOLLOWUP_MIN_RMS,
                        trigger_source=source,
                    )
                except Exception:
                    pass

            command_handled = False
            try:
                result = self.on_wake(audio)
                command_handled = result is None or bool(result)
            except Exception as e:
                print(f"[wake] on_wake handler raised: {e}")
            finally:
                # ponytail: one-line dogfooding hook — survived wake=True/False
                try:
                    # Booked against the trigger that actually started this
                    # turn. Passed in rather than read from
                    # state_manager._voice_trigger_source, because this runs
                    # later on a worker thread and trigger.py resets that back
                    # to None at end of turn — reading it here would race and
                    # silently mislabel.
                    dogfooding_ledger.record_wake(command_handled, source=source)
                except Exception:
                    pass
                if command_handled:
                    window = _FOLLOWUP_IDLE_S
                    # If the turn ended by ASKING something, keep listening.
                    # 3s begins when the assistant stops speaking, so after
                    # "I need your permission to close app. Should I proceed?"
                    # the user hears it, thinks, answers — and by then the
                    # window has shut. Reported live as "not even reading my
                    # proceed command": there was no transcript at all,
                    # because nothing was listening. Asking a question and
                    # then not waiting for the answer is its own bug.
                    try:
                        # Either kind of outstanding question. A clarification
                        # ("what would you like the message to say?") needs the
                        # same thinking room as a confirmation, and used to get
                        # none — it was not represented anywhere.
                        from backend.core.agents.pending_clarification import (
                            store as _clarification_store,
                        )

                        if (_pending_store.awaiting_answer()
                                or _clarification_store.awaiting_answer()):
                            window = settings.confirmation_followup_window_s
                    except Exception:
                        pass
                    self._open_followup(window, new_chain=new_chain)
                    self._announce_followup(window)
                else:
                    self._note_empty_capture()
                    if self._followup_open():
                        print(f"[wake] empty capture ({self._empty_in_a_row}/"
                              f"{_FOLLOWUP_MAX_EMPTY}); still listening")
                    else:
                        print(f"[wake] follow-up closed after {_FOLLOWUP_MAX_EMPTY} "
                              f"empty captures; say {self.wake_phrase!r} again")

        self._turn_thread = threading.Thread(target=_run, name="wake-turn", daemon=True)
        self._turn_thread.start()

    def _drain(self) -> None:
        while not self.queue.empty():
            try:
                self.queue.get_nowait()
            except queue.Empty:
                break

    def _capture(self, initial: Optional[list[bytes]] = None,
                 initial_is_speech: bool = True) -> bytes:
        """Read mic chunks until VAD says the user stopped speaking.

        Two phases:
          1. Wait up to _VAD_INITIAL_WAIT_S for the first speech chunk.
          2. Once speech started, accumulate chunks and stop once
             _VAD_TRAILING_SILENCE_MS of silence has passed.
        Hard cap at _VAD_MAX_CAPTURE_S total.

        `initial` is any audio already collected by the caller (e.g. the
        chunk that triggered follow-up mode, or audio that arrived during
        wake recognition). It seeds the buffer so we don't lose it.
        """
        bytes_per_second = self.sample_rate * 2  # int16 mono
        max_total_bytes = int(_VAD_MAX_CAPTURE_S * bytes_per_second)
        silence_threshold_bytes = (_VAD_TRAILING_SILENCE_MS / 1000) * bytes_per_second
        initial_wait_bytes = int(_VAD_INITIAL_WAIT_S * bytes_per_second)

        chunks: list[bytes] = list(initial or [])
        total_bytes = sum(len(c) for c in chunks)
        speech_seen = False
        trailing_silence_bytes = 0
        bytes_before_speech = 0

        # Account for any speech in the initial chunks already.
        #
        # initial_is_speech=False for the wake pre-roll. That audio is the WAKE
        # WORD, not the command -- counting it as speech arms the
        # trailing-silence rule before the user has started the command, so
        # "onyx" ... <a beat> ... "open notepad" ends the capture during the
        # beat and the command is never recorded. Follow-up and barge-in pass
        # True, because there the triggering frame really IS the command.
        for c in (chunks if initial_is_speech else []):
            arr = np.frombuffer(c, dtype=np.int16)
            if arr.size and float(np.sqrt(np.mean(arr.astype(np.float32) ** 2))) > _CAPTURE_SILENCE_THRESHOLD:
                speech_seen = True
                break

        while total_bytes < max_total_bytes:
            try:
                # The queue carries (frame_start, pcm) since the pre-roll trim
                # needed callback-time stamps; capture only wants the audio.
                _frame_start, chunk = self.queue.get(timeout=2.0)
            except queue.Empty:
                break

            arr = np.frombuffer(chunk, dtype=np.int16)
            if arr.size == 0:
                continue
            rms = float(np.sqrt(np.mean(arr.astype(np.float32) ** 2)))
            # Capture gate, not the wake gate — see _CAPTURE_SILENCE_THRESHOLD.
            is_speech = rms > _CAPTURE_SILENCE_THRESHOLD

            chunks.append(chunk)
            total_bytes += len(chunk)

            if is_speech:
                speech_seen = True
                trailing_silence_bytes = 0
            else:
                if speech_seen:
                    trailing_silence_bytes += len(chunk)
                    if trailing_silence_bytes >= silence_threshold_bytes:
                        break
                else:
                    bytes_before_speech += len(chunk)
                    if bytes_before_speech >= initial_wait_bytes:
                        # User never started talking — bail rather than hang.
                        break

        return b"".join(chunks)

    def _capture_chunks(self, initial: Optional[list[bytes]] = None) -> Generator[bytes, None, None]:
        """Yield mic chunks until VAD says the user stopped speaking.
        
        Generator version for streaming STT integration.
        """
        bytes_per_second = self.sample_rate * 2  # int16 mono
        max_total_bytes = int(_VAD_MAX_CAPTURE_S * bytes_per_second)
        silence_threshold_bytes = (_VAD_TRAILING_SILENCE_MS / 1000) * bytes_per_second
        initial_wait_bytes = int(_VAD_INITIAL_WAIT_S * bytes_per_second)

        chunks: list[bytes] = list(initial or [])
        total_bytes = sum(len(c) for c in chunks)
        speech_seen = False
        trailing_silence_bytes = 0
        bytes_before_speech = 0

        # Account for any speech in the initial chunks already.
        for c in chunks:
            arr = np.frombuffer(c, dtype=np.int16)
            if arr.size and float(np.sqrt(np.mean(arr.astype(np.float32) ** 2))) > _CAPTURE_SILENCE_THRESHOLD:
                speech_seen = True
                break

        while total_bytes < max_total_bytes:
            try:
                # The queue carries (frame_start, pcm) since the pre-roll trim
                # needed callback-time stamps; capture only wants the audio.
                _frame_start, chunk = self.queue.get(timeout=2.0)
            except queue.Empty:
                break

            arr = np.frombuffer(chunk, dtype=np.int16)
            if arr.size == 0:
                continue
            rms = float(np.sqrt(np.mean(arr.astype(np.float32) ** 2)))
            # Capture gate, not the wake gate — see _CAPTURE_SILENCE_THRESHOLD.
            is_speech = rms > _CAPTURE_SILENCE_THRESHOLD

            chunks.append(chunk)
            total_bytes += len(chunk)

            yield chunk  # Yield each chunk for streaming STT

            if is_speech:
                speech_seen = True
                trailing_silence_bytes = 0
            else:
                if speech_seen:
                    trailing_silence_bytes += len(chunk)
                    if trailing_silence_bytes >= silence_threshold_bytes:
                        break
                else:
                    bytes_before_speech += len(chunk)
                    if bytes_before_speech >= initial_wait_bytes:
                        break

    def listen(self) -> None:
        """Continuously listen for wake word and fire callbacks."""
        self._running = True
        print(f"[wake] listening for {self.wake_phrase!r}... (Ctrl+C to stop)")
        # Smaller blocksize (125ms) gives PartialResult more frequent updates
        # AND lets follow-up RMS triggering react fast. Trade-off: more CPU.
        with sd.RawInputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype="int16",
            blocksize=WAKE_BLOCKSIZE,
            device=self.device,
            callback=self._cb,
        ) as stream:
            # Now that the device is open, its reported latency completes the
            # frame-start estimate _cb needs. Measured 125ms on MME here,
            # exactly one blocksize. Guarded: `latency` is host-API dependent
            # and a missing value must not stop the listener from running.
            try:
                self._frame_lead_s = (WAKE_BLOCKSIZE / float(self.sample_rate)
                                      + float(stream.latency))
            except Exception:
                pass
            # Persists ACROSS frames on purpose: PartialResult is cumulative,
            # so the token-growth gates need the previous frame's string as a
            # baseline. Re-initialising it per frame would make every loud
            # frame after a quiet one look like fresh speech.
            partial: str = ""

            while self._running:
                try:
                    frame_start, data = self.queue.get(timeout=0.5)
                except queue.Empty:
                    continue
                if self._capturing:
                    continue

                now = time.monotonic()
                in_followup = self._followup_open()

                trigger = False
                is_barge_in = False
                is_wake_preroll = False
                # Only a wake word (or barge-in) starts a fresh chain; a turn
                # triggered from inside the window must not reset the ceiling
                # that bounds it.
                from_followup = False
                initial_audio: list[bytes] = []
                trigger_label = ""

                # Keep every frame briefly. The recognizer needs several
                # frames before it will say "onyx", and by then the user is
                # already partway through the command -- those frames ARE the
                # command, not preamble.
                self._preroll.append((frame_start, data))

                arr = np.frombuffer(data, dtype=np.int16)
                rms = float(np.sqrt(np.mean(arr.astype(np.float32) ** 2))) if arr.size else 0

                try:
                    if rms > _VAD_RMS_THRESHOLD:
                        partial = feed_wake_chunk(self.recognizer, data)

                        if (wake_phrase_present(partial, self.wake_phrase)
                                and self._wake_trigger_allowed(rms)):
                            trigger = True
                            # Everything the recognizer consumed getting here.
                            initial_audio = [d for _, d in self._preroll]
                            is_wake_preroll = True
                            trigger_label = f"wake: {partial!r} (rms={rms:.0f})"
                            # Archive the audio that FIRED the wake, separately
                            # from the command capture. Replaying the command
                            # captures re-detected 'onyx' in only 1 of 41, so
                            # there was no way to measure a false-fire rate —
                            # the evidence for the decision was never kept.
                            # Same directory, same gitignore, own retention
                            # budget (see capture_archive._BUCKET_PREFIX).
                            try:
                                from backend.core import capture_archive

                                capture_archive.archive(
                                    b"".join(initial_audio), "",
                                    trigger="wake", dispatched=True,
                                    extra={"bucket": "wake_trigger",
                                           "partial": partial,
                                           "rms": round(rms)},
                                )
                            except Exception:
                                pass
                            self.recognizer.Reset()
                            partial = ""
                            self._partial_tokens = 0
                            self._empty_in_a_row = 0
                            state_manager._voice_trigger_source = "wake"
                        elif (in_followup
                                and _partial_grew(partial, self._partial_tokens)
                                and self._followup_trigger(rms)):
                            # T-wake-word-executes-ambient-audio item 2: gate the
                            # follow-up window on CONTENT, not loudness. Near-silence
                            # after the speaker cut off still clears rms>500 and
                            # Whisper hallucinated whole commands on it ("I am
                            # working out." ran a full LLM turn). Vosk decodes no
                            # tokens from that audio, so the count does not move.
                            #
                            # This was _has_followup_content, which asked for
                            # alphabetic words. Under our restricted grammar the
                            # user's actual words arrive as "[unk]" and that check
                            # is False for every frame of real speech — measured —
                            # so the follow-up window only ever reopened on a second
                            # "onyx", which is just the wake path.
                            trigger = True
                            from_followup = True
                            trigger_label = f"followup: {partial!r} (rms={rms:.0f})"
                            # Seeded with [data] alone until 2026-09-22, which
                            # discarded everything said while Vosk was still
                            # accumulating evidence — a measured 880ms, turning
                            # "Introduce yourself" into "yourself".
                            #
                            # The pre-roll cannot be used raw: it keeps filling
                            # during playback (_capturing is cleared before the
                            # turn body runs) and there is no AEC, so it can
                            # hold Onyx's own voice. Trimmed per frame against
                            # the end of playback; `data` is always kept, so
                            # this is never worse than the old behaviour.
                            from backend.ai_modules.speech.tts_piper import (
                                speech_boundary,
                            )

                            initial_audio = clean_preroll(
                                list(self._preroll)[:-1], speech_boundary(),
                            ) + [data]
                            state_manager._voice_trigger_source = "followup"
                            self.recognizer.Reset()
                            partial = ""
                            self._partial_tokens = 0

                except Exception:
                    continue

                # Phase 4A: barge-in — if the user speaks WHILE TTS is playing,
                # interrupt playback and treat the utterance as a new command.
                # RMS + debounce is a coarse mitigation for TTS-bleeding-into-
                # mic false-fires; a loud speaker close to the mic will still
                # false-fire (out of scope — future AEC work).
                if not trigger and self._check_barge_in(rms, partial):
                    trigger = True
                    is_barge_in = True
                    trigger_label = f"barge-in (rms={rms:.0f})"
                    initial_audio = [data]
                    state_manager._voice_trigger_source = "barge_in"

                if not trigger:
                    continue

                print(f"[wake] heard {trigger_label}")
                self._capturing = True
                # Route the pre-capture callback: barge-in gets its own hook
                # (so the trigger can also publish SpeechInterruptedEvent),
                # falling back to on_wake_detected for the normal wake path.
                if is_barge_in and self.on_barge_in is not None:
                    try:
                        self.on_barge_in(rms)
                    except Exception as e:
                        print(f"[wake] on_barge_in raised: {e}")
                elif self.on_wake_detected is not None:
                    try:
                        self.on_wake_detected()
                    except Exception as e:
                        print(f"[wake] on_wake_detected raised: {e}")

                # Capture stays inline: it reads the same mic queue this loop
                # does, so they cannot both run.
                try:
                    # Wake pre-roll is the wake WORD, not the command --
                    # see _capture's initial_is_speech.
                    audio = self._capture(initial=initial_audio,
                                          initial_is_speech=not is_wake_preroll)
                except Exception as e:
                    print(f"[wake] capture raised: {e}")
                    audio = b""
                finally:
                    try:
                        self.recognizer.Reset()
                    except Exception:
                        pass
                    # Reset() empties PartialResult; the growth baseline has to
                    # follow it down or the next utterance's first tokens look
                    # like no growth at all.
                    partial = ""
                    self._partial_tokens = 0
                    self._barge_in_saw_speech = False
                    self._drain()
                    # Cleared HERE, not after the turn. Holding it until
                    # on_wake returned made the listener deaf for the entire
                    # reply — see _run_turn.
                    self._capturing = False

                # The turn — planning, tools, and every spoken sentence — runs
                # on a worker so this loop keeps reading the mic. That is what
                # makes barge-in and "stop" possible at all while speaking.
                self._start_turn(
                    audio,
                    new_chain=not from_followup,
                    source=("barge_in" if is_barge_in
                            else "followup" if from_followup else "wake"),
                    # The RMS of the frame that fired this turn — the number
                    # the follow-up gate compares against _FOLLOWUP_MIN_RMS,
                    # and the one the archive could not previously record.
                    rms=rms,
                )

    def stop(self) -> None:
        self._running = False
