"""Where SG-CUBE reads its code, finds its models, and writes its state.

APP_ROOT is the install directory: code, prompts, the built frontend. On an
installed copy it sits under Program Files, which a normal user cannot write
to, so nothing mutable may live there.

DATA_DIR is everything the app writes: memory, logs, captures, contacts, the
user's .env. Resolution order:

  1. SG_CUBE_HOME, if set.
  2. A dev checkout (APP_ROOT has .git) keeps writing to APP_ROOT/backend, so
     the existing layout — and the existing memory — stays exactly where it is.
  3. Otherwise %LOCALAPPDATA%\\SG-CUBE.

Models (Vosk, Piper) resolve separately, because they are not state: they are
large, downloaded once, and identical for every run. Tying them to DATA_DIR
meant pointing SG_CUBE_HOME at a temp dir (as the test suite does) also hid the
real models, silently skipping every real-audio test. Resolution order:

  1. SG_CUBE_MODELS, if set.
  2. A dev checkout keeps the historical backend/ai_modules/speech folders.
  3. Otherwise DATA_DIR/models.

Modules keep their own module-level path constants (tests monkeypatch those);
they are just initialised from here instead of from __file__.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping

APP_ROOT = Path(__file__).resolve().parents[2]


def resolve(env: Mapping[str, str], app_root: Path) -> dict[str, Path]:
    dev = (app_root / ".git").exists()

    if env.get("SG_CUBE_HOME"):
        data = Path(env["SG_CUBE_HOME"])
    elif dev:
        data = app_root / "backend"
    else:
        local = env.get("LOCALAPPDATA")
        data = (Path(local) if local else Path.home() / "AppData" / "Local") / "SG-CUBE"

    if env.get("SG_CUBE_MODELS"):
        models = Path(env["SG_CUBE_MODELS"])
        vosk, piper = models / "vosk", models / "piper"
    elif dev:
        speech = app_root / "backend" / "ai_modules" / "speech"
        vosk, piper = speech / "vosk_models", speech / "piper_voices"
    else:
        vosk, piper = data / "models" / "vosk", data / "models" / "piper"

    return {
        "DATA_DIR": data,
        "DB_DIR": data / "database",
        "LOG_DIR": data / "logs",
        "CHROMA_DIR": data / "database" / "chroma_db",
        "VOSK_DIR": vosk,
        "PIPER_DIR": piper,
        # User-level config written by first-run setup, loaded after
        # APP_ROOT/.env so it wins. An unredirected dev checkout has only the
        # one .env, at the repo root.
        "USER_ENV": app_root / ".env" if data == app_root / "backend" else data / ".env",
    }


_resolved = resolve(os.environ, APP_ROOT)

DATA_DIR = _resolved["DATA_DIR"]
DB_DIR = _resolved["DB_DIR"]
LOG_DIR = _resolved["LOG_DIR"]
CHROMA_DIR = _resolved["CHROMA_DIR"]
VOSK_DIR = _resolved["VOSK_DIR"]
PIPER_DIR = _resolved["PIPER_DIR"]
USER_ENV = _resolved["USER_ENV"]
