from functools import lru_cache
from pathlib import Path

from faster_whisper import WhisperModel

from backend.server.config import settings


@lru_cache(maxsize=1)
def get_model() -> WhisperModel:
    """Load Whisper once, cache for the process lifetime.

    Defaults: CPU + int8 — works on any machine without CUDA.
    Switch to device='cuda' + compute_type='float16' if you have a GPU.
    First call downloads the model weights (~140MB for 'base').
    """
    return WhisperModel(
        settings.whisper_model,
        device="cpu",
        compute_type="int8",
    )


# Initial-prompt biasing for Whisper. Single-word commands ("lock",
# "next", "stop") often get rewritten to common everyday words ("luck",
# "neck") because they have no context. The prompt below is prose-style
# (NOT a comma-separated list — comma lists teach Whisper to split words
# like "notepad" into "note, pad"). Reads as if a previous user just
# spoke similar commands, which is how Whisper's prompt mechanism is
# designed to work.
_COMMAND_PROMPT = (
    "I am using a voice assistant. I say things like open notepad, "
    "close chrome, lock the screen, play music on youtube, search google, "
    "what time is it, whats the weather, read the news, set a reminder, "
    "translate this to spanish, summarize this article. The assistant "
    "controls notepad, chrome, firefox, vscode, spotify, whatsapp, "
    "discord, telegram, calculator, explorer, and other apps."
)


def transcribe(audio_path: str | Path) -> dict:
    """Transcribe a short voice-command clip.

    Tuned for ~2s English command audio:
      - language="en" — skip Whisper's language-detect pass (~200ms saved,
        avoids occasional misidentification on noisy short clips).
      - beam_size=1 — greedy decoding. Beam search helps with long-form
        audio; for 1-3 word commands it's strictly slower with no gain.
      - vad_filter=True — drop silence/noise around the spoken bit so the
        decoder only sees the audio that matters. Big speedup when the user
        speaks for <1s inside a 2.5s capture window.
      - initial_prompt — biases decoding toward command vocabulary so
        "lock" doesn't come through as "luck" / "next" as "neck", etc.
    """
    model = get_model()
    segments, info = model.transcribe(
        str(audio_path),
        language="en",
        beam_size=1,
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 300},
        initial_prompt=_COMMAND_PROMPT,
    )

    valid_segments = []
    for seg in segments:
        # Filter out segments that are likely noise or hallucinations.
        # avg_logprob: higher is better (0 is perfect, -1 is okay, -3 is bad).
        # no_speech_prob: lower is better (0 is speech, 1 is noise).
        if seg.no_speech_prob > 0.6 or seg.avg_logprob < -1.5:
            continue
            
        cleaned = seg.text.strip()
        # Whisper often hallucinations "Thank you." or "you" when it hears
        # static/noise. If the segment is extremely short and low confidence,
        # drop it.
        if cleaned.lower() in ["thank you.", "you", "thanks.", "bye."]:
            if seg.avg_logprob < -0.5:
                continue

        valid_segments.append(cleaned)

    text = " ".join(valid_segments).strip()
    return {
        "text": text,
        "language": info.language,
        "language_probability": round(float(info.language_probability), 4),
        "duration_sec": round(float(info.duration), 3),
    }
