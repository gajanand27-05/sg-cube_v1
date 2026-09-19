"""Is local Ollama up, and does the user know when it isn't?

A dead local Ollama is the single most misleading failure in this system. The
verifier is fail-closed, so when it cannot reach a model it rejects the tool
call — and the user hears "action rejected", which is indistinguishable from
being misheard. Verification, intent, summarization and embeddings all route
local, so one dead service degrades four subsystems silently.

This module does three things:
  - probe, and try to START Ollama if it is down (detached, so it outlives us)
  - remember whether we are currently offline
  - hand out a spoken notice EXACTLY ONCE per transition, in each direction

The announcement is a pull, not a push: callers ask `take_announcement()` and
speak the line themselves. Speaking from here would mean making sound from
whatever thread or loop happened to notice the failure, and tts_piper.speak is
fire-and-forget under a running loop — the STT-unavailable notice was silent in
production for exactly that reason. The turn already knows how to speak.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)

_lock = threading.Lock()
_offline = False           # last known state
_pending: str | None = None  # a line owed to the user, or None

OFFLINE_LINE = (
    "My local models are offline, so I can't verify actions right now. "
    "Start Ollama and I'll pick it up."
)
RECOVERED_LINE = "Local models are back online."

# Survives the daemon. See _record_restart for why a log line is not enough.
_RESTART_LOG = Path(__file__).resolve().parents[1] / "logs" / "ollama_restarts.jsonl"

# Where Ollama installs on Windows when it is not on PATH. `where ollama`
# found it here while the service itself was not running, so PATH absence is
# not evidence of absence.
_WINDOWS_DEFAULT = os.path.expandvars(
    r"%LOCALAPPDATA%\Programs\Ollama\ollama.exe"
)


def _base_url() -> str:
    from backend.server.config import settings
    return (settings.ollama_url or "http://127.0.0.1:11434").rstrip("/")


def is_reachable(timeout: float = 2.0) -> bool:
    """One cheap GET. Never raises."""
    try:
        import httpx

        r = httpx.get(f"{_base_url()}/api/tags", timeout=timeout)
        return r.status_code == 200
    except Exception:
        return False


def _binary() -> str | None:
    found = shutil.which("ollama")
    if found:
        return found
    return _WINDOWS_DEFAULT if os.path.exists(_WINDOWS_DEFAULT) else None


def try_start() -> bool:
    """Launch `ollama serve` DETACHED. Returns True if it was spawned.

    Detached matters: started as an ordinary child it dies with the daemon,
    so a restart of Jarvis would take the local models down with it and the
    next boot would "fix" a problem it had caused. On Windows that needs
    DETACHED_PROCESS|CREATE_NEW_PROCESS_GROUP; elsewhere, start_new_session.
    """
    exe = _binary()
    if not exe:
        log.warning("ollama binary not found; cannot start local models")
        return False
    try:
        kwargs: dict = {
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
            "stdin": subprocess.DEVNULL,
        }
        if os.name == "nt":
            kwargs["creationflags"] = (
                getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
                | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
            )
        else:
            kwargs["start_new_session"] = True
        subprocess.Popen([exe, "serve"], **kwargs)
        log.info("spawned detached: %s serve", exe)
        return True
    except Exception as e:
        log.warning("could not start ollama: %s", e)
        return False


def _record_restart(outcome: str, seconds: float | None = None) -> None:
    """Append one line to a restart ledger that OUTLIVES the daemon.

    A log.warning would answer "did it restart" but not "does something keep
    killing it" — nothing configures file logging in this project, so console
    output dies with the process that wrote it. The pattern is the whole
    question: one restart after a reboot is normal, six in an afternoon means
    something is killing Ollama and that is a different bug entirely.
    """
    try:
        _RESTART_LOG.parent.mkdir(parents=True, exist_ok=True)
        with _RESTART_LOG.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({
                "at": datetime.now().astimezone().isoformat(timespec="seconds"),
                "outcome": outcome,
                "came_up_after_s": round(seconds, 1) if seconds is not None else None,
            }) + "\n")
    except Exception as e:
        log.debug("could not record ollama restart: %s", e)


def ensure_running(wait_s: float = 30.0) -> bool:
    """Probe; start it if down; poll until it answers or `wait_s` elapses.

    30s, not the 12s this shipped with for an hour: a measured cold start on
    this machine took 18.1s. At 12s the wait expired while Ollama was still
    coming up, so it announced "local models are offline" about a service that
    was seconds from answering — a false alarm is worse than no alarm, because
    it teaches the user to ignore the real one. This runs on a background
    preload thread, so waiting longer costs nothing.
    """
    if is_reachable():
        note_reachable()
        return True
    log.warning("local Ollama unreachable at %s — attempting to start it",
                datetime.now().astimezone().isoformat(timespec="seconds"))
    if not try_start():
        _record_restart("spawn_failed")
        note_unreachable()
        return False
    t0 = time.monotonic()
    deadline = t0 + wait_s
    while time.monotonic() < deadline:
        if is_reachable(timeout=1.5):
            took = time.monotonic() - t0
            log.warning("local Ollama AUTO-RESTARTED at %s (up after %.1fs)",
                        datetime.now().astimezone().isoformat(timespec="seconds"), took)
            _record_restart("restarted", took)
            note_reachable()
            return True
        time.sleep(0.75)
    log.error("local Ollama did not come up within %.0fs", wait_s)
    _record_restart("timeout")
    note_unreachable()
    return False


def note_unreachable() -> None:
    """Record that local models are down; queue the notice once."""
    global _offline, _pending
    with _lock:
        if not _offline:
            _offline = True
            _pending = OFFLINE_LINE
            log.warning("local models OFFLINE")


def note_reachable() -> None:
    """Record that local models are up; queue the recovery notice once."""
    global _offline, _pending
    with _lock:
        if _offline:
            _offline = False
            _pending = RECOVERED_LINE
            log.info("local models RECOVERED")


def note_failure_if_local_is_down() -> bool:
    """Call from a failure handler. Probes rather than guessing.

    Deciding from the exception text would mean string-matching httpx and
    ollama error shapes and getting it wrong on the one that matters. A local
    GET costs nothing and answers the actual question: is Ollama up? Returns
    True when the failure is attributable to local models being down.
    """
    if is_reachable(timeout=1.5):
        note_reachable()
        return False
    note_unreachable()
    return True


def take_announcement() -> str | None:
    """The line owed to the user, once. Subsequent calls return None until
    the state changes again — that is what keeps a persistent outage from
    being re-announced on every single turn."""
    global _pending
    with _lock:
        line, _pending = _pending, None
        return line
