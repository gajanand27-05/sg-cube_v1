# Help train the "Onyx" wake word (about 3 minutes)

Onyx is a voice assistant that wakes up when you say its name. It has to work
for every accent, so I'm collecting short recordings from real people. Thank
you for helping.

## What to record

Record **one voice note** (WhatsApp voice note is fine) in a normal room, with
the phone about an arm's length away. Leave a **2-second pause** between each
item. Speak naturally; don't put on an accent.

1. Say **"Onyx"** 10 times in your normal voice.
2. Say **"Onyx"** 5 times softly, as if someone is asleep nearby.
3. Say these once each:
   - "Onyx, what time is it"
   - "Onyx, open notepad"
   - "Onyx, play some music"
   - "Hey Onyx"
   - "Onyx, stop"
4. Say these once each (they sound close to Onyx, so they teach it what *not*
   to wake on): "on it", "onion", "annex", "on its way", "only six".
5. Talk for about 20 seconds about anything (your day, the weather) **without**
   saying "Onyx". Any language or mix of languages is fine.

Optional, and very useful: record the whole thing a second time from across
the room, or with a fan or TV on in the background.

## What to send

- The voice note or audio file, in any format your phone makes (WhatsApp
  voice note, .m4a, .mp3, .wav).
- One line with: your first name (or a nickname), your first language, and
  your state or country. For example: *"Priya, Kannada, Karnataka"*.
- The consent line below, copied into your message.

## Consent

> I agree that my recording may be used to train and test the Onyx wake word,
> including in a product that may be sold. My recording will not be published
> or shared as audio. I can ask for it to be deleted at any time.

Only send it if you agree. Your recording stays on the developer's computer
and is used only to train and test the wake word.

---

## For the developer: clip format and import

Contributors can send anything their phone produces. `tools/import_wake_clips.py`
decodes it (PyAV, already installed) to what the wake-word bench and training
use: **16 kHz, mono, 16-bit PCM WAV**, one utterance per file.

```
.venv\Scripts\python.exe tools\import_wake_clips.py "Priya_voice-note.opus" --speaker priya --lang kannada --region karnataka
```

It splits the recording at the pauses, saves each utterance under
`tools/_wake/contrib/<speaker>/` (git-ignored), and writes `manifest.json`
with each clip's timing, a transcription guess and a suggested label
(`onyx`, `near_miss` or `other`) for you to check. Keep each contributor's
consent message with their files.
