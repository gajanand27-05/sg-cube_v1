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

# Counters that are also tracked inside the resettable window.
#
# Why a window exists at all: the lifetime counters run from the first ever
# launch, so they blend every era the assistant has been through — the
# turn-stale bug, the OpenRouter 402 period, the day the embedding backend was
# down, the TTS loop crash. At the time this was added they read 77 successes
# in 2138 wake attempts with 588 crashes, which says nothing whatsoever about
# the build you are running now.
#
# Three tickets (T-barge-in-tuning, T-tool-surface-pruning,
# T-latency-optimization) are explicitly gated on "use it for a day, then read
# the numbers". That is unanswerable from a lifetime total, so it stays AND a
# window you can zero at a known-good commit sits beside it.
_WINDOWED = (
    "wake_attempts", "wake_successes",
    "command_total", "command_success",
    "tools_total", "tools_success",
    "crashes", "total_command_latency_ms",
)


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _pct_or_none(num: int, denom: int) -> float | None:
    # None means "no data yet" — distinguish from 0% which means "actively broken"
    return round(num / denom * 100, 2) if denom else None


def _rates(d: dict[str, Any]) -> dict[str, Any]:
    """Rates from a counter dict — used for both lifetime and window."""
    cmd_t = d.get("command_total", 0)
    return {
        "wake_success_pct":    _pct_or_none(d.get("wake_successes", 0), d.get("wake_attempts", 0)),
        "command_success_pct": _pct_or_none(d.get("command_success", 0), cmd_t),
        "tool_success_pct":    _pct_or_none(d.get("tools_success", 0), d.get("tools_total", 0)),
        "crash_rate_pct":      _pct_or_none(d.get("crashes", 0), cmd_t),
        "avg_command_latency_ms": (
            round(d.get("total_command_latency_ms", 0) / cmd_t) if cmd_t else None
        ),
    }


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
        # An existing ledger has no window: start one now rather than
        # back-filling it from lifetime totals, which would import exactly the
        # history the window exists to exclude.
        win = self._data.setdefault("window", {})
        win.setdefault("started_at", _utcnow())
        win.setdefault("label", None)
        for k in _WINDOWED:
            win.setdefault(k, 0)
        self._save()

    def _bump(self, key: str, n: int = 1) -> None:
        """Increment a counter in both the lifetime total and the window.
        Caller holds the lock."""
        self._data[key] = self._data.get(key, 0) + n
        if key in _WINDOWED:
            win = self._data["window"]
            win[key] = win.get(key, 0) + n

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
            self._bump("wake_attempts")
            if success:
                self._bump("wake_successes")
            self._save()

    def record_command(self, success: bool, latency_ms: int = 0) -> None:
        with self._lock:
            self._bump("command_total")
            self._bump("total_command_latency_ms", latency_ms)
            if success:
                self._bump("command_success")
            if not self._data["first_command_at"]:
                self._data["first_command_at"] = _utcnow()
            self._data["last_command_at"] = _utcnow()
            self._save()

    def record_tool(self, success: bool, latency_ms: int = 0) -> None:
        with self._lock:
            self._bump("tools_total")
            if success:
                self._bump("tools_success")
            self._save()

    def record_crash(self) -> None:
        with self._lock:
            self._bump("crashes")
            self._save()

    def reset_window(self, label: str | None = None) -> dict[str, Any]:
        """Zero the measurement window and start a new one.

        Call this at a known-good commit before a real day of use, so the
        data-gated tickets can be aimed at the build you are actually running.
        Lifetime counters are deliberately untouched — the history is real,
        it is simply not an answer to "how is it behaving now".
        """
        with self._lock:
            self._data["window"] = {
                "started_at": _utcnow(),
                "label": label,
                **{k: 0 for k in _WINDOWED},
            }
            self._save()
            return dict(self._data["window"])

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

        d["rates"] = _rates(d)
        d["rates"]["current_session_id"] = d.get("session_id")
        # Same arithmetic over the window, so the two are directly comparable
        # and nobody has to work out which totals a percentage came from.
        win = d.get("window", {})
        d["window_rates"] = _rates(win)
        d["window_rates"]["started_at"] = win.get("started_at")
        d["window_rates"]["label"] = win.get("label")
        return d


ledger = Ledger()
