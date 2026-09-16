# SG_CUBE — UI Assets

Drop-in asset for the Phase 9 daemon. Optional — the daemon generates a
fallback at runtime if the file is missing.

## `chime.wav`
**Used by:** `backend/daemon/trigger.py`
**Purpose:** Short audio cue played the moment the wake phrase is heard.
**Spec:** WAV, mono, 16-bit PCM, **< 500 ms long**, **16 kHz or 44.1 kHz** sample rate.
Anything longer pads the latency between wake and command-recording.

**Fallback if missing:** `winsound.Beep(880, 120)` — a sine tone.

## Tips for picking a chime
- Make it short — under 250 ms feels snappy.
- Use a tone that doesn't sit in the same frequency range as speech (300-3000 Hz)
  so you can still hear the recording-confirmation while you're talking.
- Examples that work well: a soft "bell", "ping", or two-tone "boop-beep".
