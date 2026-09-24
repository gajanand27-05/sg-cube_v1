"""Where SG-CUBE writes. An installed copy lives under Program Files, which a
normal user cannot write to, so every mutable file must resolve outside the
install directory — while a dev checkout keeps writing where it always has."""
from pathlib import Path

from backend.core import paths


def _checkout(tmp_path):
    (tmp_path / ".git").mkdir(parents=True)
    return tmp_path


def test_explicit_home_wins(tmp_path):
    app = _checkout(tmp_path / "app")
    home = tmp_path / "home"
    got = paths.resolve({"SG_CUBE_HOME": str(home)}, app)
    assert got["DATA_DIR"] == home
    assert got["USER_ENV"] == home / ".env"


def test_dev_checkout_keeps_the_historical_layout(tmp_path):
    # Exactly the paths the modules used before paths.py existed — otherwise
    # an upgrade silently starts a fresh, empty memory next to the old one.
    app = _checkout(tmp_path)
    got = paths.resolve({}, app)
    backend = app / "backend"
    assert got["DB_DIR"] == backend / "database"
    assert got["LOG_DIR"] == backend / "logs"
    assert got["CHROMA_DIR"] == backend / "database" / "chroma_db"
    assert got["VOSK_DIR"] == backend / "ai_modules" / "speech" / "vosk_models"
    assert got["PIPER_DIR"] == backend / "ai_modules" / "speech" / "piper_voices"
    assert got["USER_ENV"] == app / ".env"


def test_installed_copy_uses_localappdata(tmp_path):
    local = tmp_path / "Local"
    got = paths.resolve({"LOCALAPPDATA": str(local)}, tmp_path / "app")
    assert got["DATA_DIR"] == local / "SG-CUBE"
    assert got["DB_DIR"] == local / "SG-CUBE" / "database"
    assert got["VOSK_DIR"] == local / "SG-CUBE" / "models" / "vosk"
    assert got["PIPER_DIR"] == local / "SG-CUBE" / "models" / "piper"
    assert got["USER_ENV"] == local / "SG-CUBE" / ".env"


def test_installed_copy_without_localappdata_falls_back_to_home(tmp_path):
    got = paths.resolve({}, tmp_path / "app")
    assert got["DATA_DIR"] == Path.home() / "AppData" / "Local" / "SG-CUBE"


def test_redirecting_data_keeps_the_checkouts_models(tmp_path):
    # The suite points SG_CUBE_HOME at a temp dir. If models followed it, every
    # real-audio test would quietly skip for want of a Vosk model.
    app = _checkout(tmp_path / "app")
    got = paths.resolve({"SG_CUBE_HOME": str(tmp_path / "home")}, app)
    assert got["VOSK_DIR"] == app / "backend" / "ai_modules" / "speech" / "vosk_models"


def test_explicit_models_dir_wins(tmp_path):
    models = tmp_path / "m"
    got = paths.resolve({"SG_CUBE_MODELS": str(models)}, _checkout(tmp_path / "app"))
    assert got["VOSK_DIR"] == models / "vosk"
    assert got["PIPER_DIR"] == models / "piper"


def test_suite_runs_against_isolated_state_but_real_models():
    # conftest sets SG_CUBE_HOME before anything imports backend.
    assert paths.DATA_DIR != paths.APP_ROOT / "backend"
    assert paths.VOSK_DIR == paths.APP_ROOT / "backend" / "ai_modules" / "speech" / "vosk_models"
