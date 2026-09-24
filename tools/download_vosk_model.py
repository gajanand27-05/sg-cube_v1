"""Download a Vosk acoustic model and unpack it into paths.VOSK_DIR (see backend/core/paths.py).

Usage:
    python tools/download_vosk_model.py                       # default small English model
    python tools/download_vosk_model.py vosk-model-en-us-0.22-lgraph

Browse: https://alphacephei.com/vosk/models
"""
import io
import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend.core import paths  # noqa: E402

MODELS_DIR = paths.VOSK_DIR
DEFAULT = "vosk-model-small-en-us-0.15"
BASE = "https://alphacephei.com/vosk/models"


def download(name: str) -> None:
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    dest = MODELS_DIR / name
    if dest.exists():
        print(f"already present: {dest}")
        return

    url = f"{BASE}/{name}.zip"
    print(f"downloading {url}")
    with urllib.request.urlopen(url) as resp:
        total = int(resp.headers.get("Content-Length", 0))
        data = io.BytesIO()
        chunk = 1024 * 256
        read = 0
        while True:
            buf = resp.read(chunk)
            if not buf:
                break
            data.write(buf)
            read += len(buf)
            if total:
                pct = 100 * read / total
                print(f"  {read//1024:>6} KB / {total//1024} KB ({pct:.0f}%)", end="\r")
        print()

    print(f"unpacking into {MODELS_DIR}")
    data.seek(0)
    with zipfile.ZipFile(data) as zf:
        zf.extractall(MODELS_DIR)
    print(f"  -> {dest}")


if __name__ == "__main__":
    name = sys.argv[1] if len(sys.argv) > 1 else DEFAULT
    download(name)
