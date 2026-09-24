"""Where SG-CUBE writes. An installed copy lives under Program Files, which a
normal user cannot write to, so every mutable file must resolve outside the
install directory — while a dev checkout keeps writing where it always has."""
from pathlib import Path

from backend.core import paths


def test_explicit_home_wins(tmp_path):
    app = tmp_path / "app"
    (app / ".git").mkdir(parents=True)
    home = tmp_path / "home"
    assert paths.resolve_data_dir({"SG_CUBE_HOME": str(home)}, app) == home


def test_dev_checkout_keeps_repo_layout(tmp_path):
    (tmp_path / ".git").mkdir()
    assert paths.resolve_data_dir({}, tmp_path) == tmp_path / "backend"


def test_installed_copy_uses_localappdata(tmp_path):
    local = tmp_path / "Local"
    got = paths.resolve_data_dir({"LOCALAPPDATA": str(local)}, tmp_path / "app")
    assert got == local / "SG-CUBE"


def test_installed_copy_without_localappdata_falls_back_to_home(tmp_path):
    got = paths.resolve_data_dir({}, tmp_path / "app")
    assert got == Path.home() / "AppData" / "Local" / "SG-CUBE"


def test_dev_layout_matches_the_historical_paths():
    # The suite runs from the checkout, so these must be exactly the paths the
    # modules used before paths.py existed — otherwise an upgrade silently
    # starts a fresh, empty memory next to the old one.
    backend = paths.APP_ROOT / "backend"
    assert paths.DB_DIR == backend / "database"
    assert paths.LOG_DIR == backend / "logs"
    assert paths.CHROMA_DIR == backend / "database" / "chroma_db"
    assert paths.VOSK_DIR == backend / "ai_modules" / "speech" / "vosk_models"
    assert paths.PIPER_DIR == backend / "ai_modules" / "speech" / "piper_voices"


def test_installed_layout_puts_models_in_data_dir(tmp_path):
    layout = paths.layout(tmp_path / "data", dev=False)
    assert layout["VOSK_DIR"] == tmp_path / "data" / "models" / "vosk"
    assert layout["PIPER_DIR"] == tmp_path / "data" / "models" / "piper"
    assert layout["DB_DIR"] == tmp_path / "data" / "database"
