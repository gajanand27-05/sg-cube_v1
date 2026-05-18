"""Notes tools (Phase 11c) — daily markdown file under ~/sg_cube/notes/."""
import subprocess
from datetime import datetime
from pathlib import Path

from backend.core.tools.registry import tool

NOTES_DIR = Path.home() / "sg_cube" / "notes"


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _notes_path(date: str) -> Path:
    return NOTES_DIR / f"{date}.md"


@tool
def take_note(text: str) -> dict:
    """Append a timestamped note to today's markdown file at
    ~/sg_cube/notes/YYYY-MM-DD.md. Use this for any "note this down", "save
    this", or "remember that" request."""
    if not text.strip():
        return {"status": "blocked", "reason": "empty note"}
    NOTES_DIR.mkdir(parents=True, exist_ok=True)
    path = _notes_path(_today())
    timestamp = datetime.now().strftime("%H:%M")
    line = f"- **{timestamp}** {text.strip()}\n"
    with path.open("a", encoding="utf-8") as f:
        f.write(line)
    return {"status": "success", "message": f"noted: {text.strip()}"}


@tool
def read_notes(date: str = "") -> dict:
    """Return the notes for a given date (YYYY-MM-DD). Defaults to today.
    Use when the user asks "what did I note today" or "what are my notes"."""
    if not date.strip():
        date = _today()
    path = _notes_path(date.strip())
    if not path.exists():
        return {"status": "blocked", "reason": f"no notes for {date}"}
    content = path.read_text(encoding="utf-8").strip()
    n = content.count("\n") + 1 if content else 0
    return {
        "status": "success",
        "message": f"{n} note(s) for {date}",
        "args": {"date": date, "content": content},
    }


@tool
def open_notes_today() -> dict:
    """Open today's notes file in the default markdown editor."""
    NOTES_DIR.mkdir(parents=True, exist_ok=True)
    path = _notes_path(_today())
    if not path.exists():
        path.write_text(f"# Notes — {_today()}\n\n", encoding="utf-8")
    subprocess.Popen(f'start "" "{path}"', shell=True)
    return {"status": "success", "message": f"opened {path.name}"}
