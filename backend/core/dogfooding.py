"""Persistent dogfooding ledger.

Tracks reliability counters across restarts so we can watch the voice
module stabilize over time. JSON file lives next to the existing
backend/database/ data dir; survives concurrent writes from the wake-
listener thread via a temp-file atomic-ish rename.

ponytail: JSON storage over SQLite because the counters are simple,
no time-series queries needed, and a human-readable file is easier to
diff/eyeball during dogfooding. Upgrade path: SQLite + daily rollups
if we ever need to plot a 30-day chart.
"""
import json
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_DATA_DIR = Path(__file__).resolve().parents[1] / "database"
_LEDGER_PATH = _DATA_DIR / "dogfooding.json"


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Ledger:
    def __init__(self, path: Path = _LEDGER_PATH):
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._data: dict[str, Any] = self._load()
        self._data.setdefault("started_at", _utcnow())
        self._data.setdefault("session_id", str(uuid.uuid4()))
        self._data["session_started_at"] = _utcnow()
        # ensure numeric counters exist even if file pre-dates them
        for k in (
            "wake_attempts", "wake_successes",
            "command_total", "command_success",
            "tools_total", "tools_success",
            "crashes", "p0_bugs", "p1_bugs",
            "total_command_latency_ms",
        ):
            self._data.setdefault(k, 0)
        self._data.setdefault("first_command_at", None)
        self._data.setdefault("last_command_at", None)
        self._data.setdefault("bugs", [])
        self._save()

    def _load(self) -> dict[str, Any]:
        if not self._path.exists():
            return {}
        try:
            with self._path.open("r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            # corrupt or unreadable — back it up and start fresh
            try:
                self._path.rename(self._path.with_suffix(".json.bak"))
            except OSError:
                pass
            return {}

    def _save(self) -> None:
        tmp = self._path.with_suffix(".json.tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(self._data, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self._path)

    def record_wake(self, success: bool) -> None:
        with self._lock:
            self._data["wake_attempts"] += 1
            if success:
                self._data["wake_successes"] += 1
            self._save()

    def record_command(self, success: bool, latency_ms: int = 0) -> None:
        with self._lock:
            self._data["command_total"] += 1
            self._data["total_command_latency_ms"] += latency_ms
            if success:
                self._data["command_success"] += 1
            if not self._data["first_command_at"]:
                self._data["first_command_at"] = _utcnow()
            self._data["last_command_at"] = _utcnow()
            self._save()

    def record_tool(self, success: bool, latency_ms: int = 0) -> None:
        with self._lock:
            self._data["tools_total"] += 1
            if success:
                self._data["tools_success"] += 1
            self._save()

    def record_crash(self) -> None:
        with self._lock:
            self._data["crashes"] += 1
            self._save()

    def record_bug(self, priority: str, description: str) -> dict[str, Any]:
        p = priority.upper()
        if p not in ("P0", "P1"):
            raise ValueError(f"priority must be P0 or P1, got {priority!r}")
        entry = {"ts": _utcnow(), "priority": p, "description": description}
        with self._lock:
            self._data["bugs"].append(entry)
            key = "p0_bugs" if p == "P0" else "p1_bugs"
            self._data[key] += 1
            self._save()
        return entry

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            d = dict(self._data)

        def pct_or_none(num: int, denom: int) -> float | None:
            # None means "no data yet" — distinguish from 0% which means "actively broken"
            return round(num / denom * 100, 2) if denom else None

        wake_a = d.get("wake_attempts", 0)
        cmd_t = d.get("command_total", 0)
        tool_t = d.get("tools_total", 0)
        d["rates"] = {
            "wake_success_pct":     pct_or_none(d.get("wake_successes", 0), wake_a),
            "command_success_pct":  pct_or_none(d.get("command_success", 0), cmd_t),
            "tool_success_pct":     pct_or_none(d.get("tools_success", 0), tool_t),
            "crash_rate_pct":       pct_or_none(d.get("crashes", 0), cmd_t),
            "avg_command_latency_ms": (
                round(d.get("total_command_latency_ms", 0) / cmd_t)
                if cmd_t else None
            ),
            "current_session_id":   d.get("session_id"),
        }
        return d


ledger = Ledger()
