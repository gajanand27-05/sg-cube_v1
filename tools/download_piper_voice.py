"""Download a Piper voice model + config from HuggingFace.

Usage:
    python tools/download_piper_voice.py                       # default: en_US-ryan-high
    python tools/download_piper_voice.py en_US-lessac-medium

Voice naming: <lang_country>-<speaker>-<quality>
Browse the full catalog at https://huggingface.co/rhasspy/piper-voices
"""
import sys
import urllib.request
from pathlib import Path

VOICES_DIR = (
    Path(__file__).resolve().parent.parent
    / "backend"
    / "ai_modules"
    / "speech"
    / "piper_voices"
)
BASE = "https://huggingface.co/rhasspy/piper-voices/resolve/main"


def _voice_subpath(name: str) -> str:
    lang_country, speaker, quality = name.split("-")
    lang = lang_country.split("_")[0]
    return f"{lang}/{lang_country}/{speaker}/{quality}/{name}"


def download(name: str) -> None:
    VOICES_DIR.mkdir(parents=True, exist_ok=True)
    sub = _voice_subpath(name)
    for ext in (".onnx.json", ".onnx"):
        url = f"{BASE}/{sub}{ext}"
        out = VOICES_DIR / f"{name}{ext}"
        if out.exists():
            print(f"already present: {out.name}")
            continue
        print(f"downloading {url}")
        urllib.request.urlretrieve(url, out)
        print(f"  -> {out} ({out.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    name = sys.argv[1] if len(sys.argv) > 1 else "en_US-ryan-high"
    download(name)
