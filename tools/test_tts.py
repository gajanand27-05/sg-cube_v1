"""Phase 7 verification: speak a phrase via pyttsx3.

Side effect: AUDIO OUT. Plug in headphones if you don't want speakers.

Usage:
    python tools/test_tts.py
    python tools/test_tts.py "hello from sg cube"
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.ai_modules.speech.tts_piper import speak  # noqa: E402


def main():
    text = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "hello from sg cube"
    print(f"Speaking: {text!r}")
    result = speak(text)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
