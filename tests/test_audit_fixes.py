"""Audit follow-ups that don't need a concurrency harness.

Covers: comms shell injection, intent-cache unboundedness, telemetry disk root,
confirmation-token entropy, replay dir path depth, and Runtime._tasks leak.
"""
import asyncio
import inspect
import sys
from pathlib import Path

import pytest

_project_root = Path(__file__).resolve().parents[1]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))


def _run(coro):
    """asyncio.run, but leaves a current event loop installed on the thread.

    asyncio.run() calls set_event_loop(None) on the way out. Later tests in the
    session (test_browser.py) still use the deprecated asyncio.get_event_loop(),
    which raises once the loop has been explicitly cleared. Restoring it keeps
    this file from making test order load-bearing.
    """
    try:
        return asyncio.run(coro)
    finally:
        try:
            asyncio.get_event_loop()
        except RuntimeError:
            asyncio.set_event_loop(asyncio.new_event_loop())


# ── comms.py: `subprocess.Popen(f'start "" "{url}"', shell=True)` ────────────
# `url` carries LLM/user text. `to` in send_email is only checked for "@" and
# whitespace, so `a@b.com"&calc&"x` passed validation and closed the quote in
# the generated command line. There must be no shell in this path at all.

class _Opened:
    def __init__(self):
        self.urls = []

    def open(self, url, *a, **kw):
        self.urls.append(url)
        return True


def test_comms_opens_urls_without_a_shell(monkeypatch):
    from backend.core.tools import comms

    # Comment lines dropped — the fix's own comment names the thing it removed.
    code = "\n".join(l for l in inspect.getsource(comms).splitlines()
                     if not l.lstrip().startswith("#"))
    assert "shell=True" not in code, "comms.py still spawns a shell"
    assert "subprocess" not in code, "comms.py still uses subprocess"

    spy = _Opened()
    monkeypatch.setattr(comms, "webbrowser", spy)

    injected = 'hi" & calc.exe & "'
    res = comms.send_whatsapp("+919876543210", injected)
    assert res.status.value == "success"

    # The exact injection payload that used to break out of the command line.
    res = comms.send_email('a@b.com"&calc&"x', "s", "b")
    assert res.status.value == "success"

    assert len(spy.urls) == 2
    for url in spy.urls:
        # One opaque string handed to ShellExecute — never a command line.
        assert isinstance(url, str)
    assert spy.urls[0].startswith("https://wa.me/919876543210?text=")
    assert "calc.exe" not in spy.urls[0].split("?")[0]
    # The hostile `to` survives verbatim as a single argument, which is exactly
    # the point: it is data, not a fragment of a command.
    assert spy.urls[1].startswith('mailto:a@b.com"&calc&"x?')


# ── cache_layer.py: unbounded module-level dict on the voice path ────────────

def test_intent_cache_evicts_least_recently_used():
    from backend.core.orchestrator import cache_layer
    from backend.core.orchestrator.llm_layer import Intent

    cache_layer.clear()
    try:
        for i in range(cache_layer._MAX_ENTRIES + 100):
            cache_layer.set(f"utterance {i}", Intent(action=f"a{i}"))

        assert cache_layer.size() == cache_layer._MAX_ENTRIES, "cache grew past its cap"
        assert cache_layer.get("utterance 0") is None, "oldest entry was not evicted"
        newest = cache_layer._MAX_ENTRIES + 99
        assert cache_layer.get(f"utterance {newest}") is not None

        # A key that keeps getting hit must not be evicted by newer misses.
        hot = f"utterance {newest - 10}"
        for i in range(50):
            assert cache_layer.get(hot) is not None
            cache_layer.set(f"filler {i}", Intent(action="f"))
        assert cache_layer.get(hot) is not None, "LRU evicted a hot key"
        assert cache_layer.size() == cache_layer._MAX_ENTRIES
    finally:
        cache_layer.clear()


# ── telemetry.py: psutil.disk_usage('/') ────────────────────────────────────
# On Windows '/' silently resolves against the current working directory's
# drive, so the reported disk depended on where the daemon was launched.

def test_telemetry_disk_root_is_an_absolute_drive_root():
    import psutil

    from backend.daemon.telemetry import DISK_ROOT

    assert DISK_ROOT == Path(__file__).resolve().anchor
    assert Path(DISK_ROOT).is_absolute()
    usage = psutil.disk_usage(DISK_ROOT)
    assert usage.total > 0


# ── sandbox.py: str(uuid.uuid4())[:8] — 32 bits guarding a CAUTION tool ─────

def test_confirmation_tokens_are_high_entropy():
    from backend.core.tools import sandbox
    from backend.core.tools.registry import REGISTRY, SecurityLevel

    caution = next((n for n, t in REGISTRY.items() if t.security == SecurityLevel.CAUTION), None)
    assert caution, "no CAUTION tool registered — cannot exercise the guard"

    guard = sandbox.PermissionGuard()
    tokens = {guard.check(caution, {}).data["token"] for _ in range(200)}
    assert len(tokens) == 200, "confirmation tokens collided"
    for tok in tokens:
        assert len(tok) >= 20, f"token {tok!r} is only {len(tok)} chars — too little entropy"


# ── replay.py: parents[2] / "backend" → backend/backend/database/replays ────

def test_replay_routes_and_recorder_agree_on_the_directory():
    from backend.core.replay.recorder import REPLAY_DIR as recorder_dir
    from backend.server.routes.replay import REPLAY_DIR as routes_dir

    assert routes_dir.resolve() == recorder_dir.resolve()
    # The old value was .../backend/backend/database/replays.
    assert routes_dir.resolve().parts.count("backend") == 1, f"doubled segment in {routes_dir}"


# ── runtime.py: _tasks never cleaned + unguarded task.result in finally ─────

class _Boom(BaseException):
    """Models KeyboardInterrupt/GeneratorExit: not caught by `except Exception`."""


def test_runtime_drops_finished_tasks():
    from backend.core.runtime import Runtime
    from backend.core.tools.registry import ToolResult

    rt = Runtime()

    def ok():
        return ToolResult.success("done")

    for _ in range(20):
        _run(rt.run_tool("probe", ok, {}))

    assert rt._tasks == {}, f"{len(rt._tasks)} finished tasks retained"


def test_base_exception_is_not_replaced_by_an_error_in_finally():
    from backend.core.runtime import Runtime

    rt = Runtime()

    async def explode():
        raise _Boom("original cause")

    # Pre-fix, `finally` did task.result.status.value with task.result still
    # None; the resulting AttributeError displaced _Boom entirely.
    with pytest.raises(_Boom, match="original cause"):
        _run(rt.run_tool("probe", explode, {}))

    assert rt._tasks == {}, "task leaked on the BaseException path"
