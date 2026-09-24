"""Where SG-CUBE reads its code and writes its state.

APP_ROOT is the install directory: code, prompts, the built frontend. On an
installed copy it sits under Program Files, which a normal user cannot write
to, so nothing mutable may live there.

DATA_DIR is everything the app writes: memory, logs, captures, contacts,
downloaded models, the user's .env. Resolution order:

  1. SG_CUBE_HOME, if set.
  2. A dev checkout (APP_ROOT has .git) keeps writing to APP_ROOT/backend, so
     the existing layout — and the existing memory — stays exactly where it is.
  3. Otherwise %LOCALAPPDATA%\\SG-CUBE.

Modules keep their own module-level path constants (tests monkeypatch those);
they are just initialised from here instead of from __file__.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping

APP_ROOT = Path(__file__).resolve().parents[2]


def resolve_data_dir(env: Mapping[str, str], app_root: Path) -> Path:
    if env.get("SG_CUBE_HOME"):
        return Path(env["SG_CUBE_HOME"])
    if (app_root / ".git").exists():
        return app_root / "backend"
    local = env.get("LOCALAPPDATA")
    base = Path(local) if local else Path.home() / "AppData" / "Local"
    return base / "SG-CUBE"


def layout(data_dir: Path, dev: bool) -> dict[str, Path]:
    speech = APP_ROOT / "backend" / "ai_modules" / "speech"
    return {
        "DB_DIR": data_dir / "database",
        "LOG_DIR": data_dir / "logs",
        "CHROMA_DIR": data_dir / "database" / "chroma_db",
        "VOSK_DIR": speech / "vosk_models" if dev else data_dir / "models" / "vosk",
        "PIPER_DIR": speech / "piper_voices" if dev else data_dir / "models" / "piper",
    }


DATA_DIR = resolve_data_dir(os.environ, APP_ROOT)
IS_DEV_CHECKOUT = DATA_DIR == APP_ROOT / "backend"
_layout = layout(DATA_DIR, IS_DEV_CHECKOUT)

DB_DIR = _layout["DB_DIR"]
LOG_DIR = _layout["LOG_DIR"]
CHROMA_DIR = _layout["CHROMA_DIR"]
VOSK_DIR = _layout["VOSK_DIR"]
PIPER_DIR = _layout["PIPER_DIR"]
# User-level config written by the setup wizard. Loaded after APP_ROOT/.env,
# so it wins. A dev checkout has only the one .env, at the repo root.
USER_ENV = APP_ROOT / ".env" if IS_DEV_CHECKOUT else DATA_DIR / ".env"
