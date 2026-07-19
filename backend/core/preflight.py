"""Phase 5C — startup preflight.

End-to-end readiness check: every ENABLE_*'d service actually started,
external deps (Chromium, Ollama) reachable, LLM providers registered,
and the WS bridge that ate Phase 3 is confirmed wired.

Design invariants:
  * All checks fail SAFE — a broken check returns DOWN with the exception
    text, never raises. A preflight that crashes is worse than one that
    misreports.
  * No check makes billable/quota API calls. LLM checks verify only that
    the backend is registered and reachable — actual generation happens
    lazily on first real call.
  * Each check is idempotent — safe to call repeatedly (used both at
    boot and from /diagnostics/preflight).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

log = logging.getLogger(__name__)


class PreflightStatus(str, Enum):
    OK = "ok"              # dependency is up and behaving
    DEGRADED = "degraded"  # partially working — usable but not ideal
    DOWN = "down"          # not working; feature will fail
    DISABLED = "disabled"  # ENABLE_* flag off; skipping check


@dataclass
class PreflightCheck:
    name: str
    status: PreflightStatus
    message: str
    detail: dict[str, Any] = field(default_factory=dict)


# ── Individual checks ────────────────────────────────────────────────────

def check_services() -> list[PreflightCheck]:
    """Read the per-service startup outcome from backend/daemon/main.

    Each service becomes one PreflightCheck. `failed` → DOWN,
    `disabled` → DISABLED, `started` → OK.
    """
    checks: list[PreflightCheck] = []
    try:
        from backend.daemon.main import get_service_status
        status = get_service_status()
    except Exception as e:
        return [PreflightCheck("services", PreflightStatus.DOWN,
                               f"could not read service status: {e}")]

    for name, entry in sorted(status.items()):
        raw = (entry.get("status") or "").lower()
        err = entry.get("error")
        if raw == "started":
            checks.append(PreflightCheck(f"service:{name}", PreflightStatus.OK,
                                         "started", detail={"started_at": entry.get("started_at")}))
        elif raw == "disabled":
            checks.append(PreflightCheck(f"service:{name}", PreflightStatus.DISABLED,
                                         "disabled by config flag"))
        else:
            checks.append(PreflightCheck(f"service:{name}", PreflightStatus.DOWN,
                                         f"start failed: {err or 'unknown'}"))
    return checks


def check_ws_bridge() -> PreflightCheck:
    """The load-bearing Phase 3 catch: force _setup_event_bridge() and
    verify the flag flips. If this reports OK, the bug where
    UIEventManager never subscribed to the bus (silently dropping every
    canvas/agent/tts event) cannot happen — the setup path is reachable
    and idempotent."""
    try:
        from backend.server.ws_ui import get_manager
        mgr = get_manager()
        mgr._setup_event_bridge()  # idempotent
        if not mgr._bridge_setup:
            return PreflightCheck("ws_bridge", PreflightStatus.DOWN,
                                  "_setup_event_bridge ran but flag not set — bus subscription lost")
        n = len(mgr._connections)
        return PreflightCheck("ws_bridge", PreflightStatus.OK,
                              "event bus → WS subscription active",
                              detail={"connections": n})
    except Exception as e:
        return PreflightCheck("ws_bridge", PreflightStatus.DOWN,
                              f"bridge setup raised: {type(e).__name__}: {e}")


def check_browser() -> PreflightCheck:
    """Chromium presence when ENABLE_BROWSER. Playwright itself is a
    Python package (so `import playwright` almost always works) — the
    real question is whether the Chromium binary is installed. We check
    for the binary path via the sync API."""
    from backend.server.config import settings
    if not settings.enable_browser:
        return PreflightCheck("browser", PreflightStatus.DISABLED,
                              "ENABLE_BROWSER=false")
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as e:
        return PreflightCheck("browser", PreflightStatus.DOWN,
                              f"playwright package missing: {e}")
    try:
        with sync_playwright() as p:
            # executable_path throws if the Chromium download is absent.
            path = p.chromium.executable_path
        return PreflightCheck("browser", PreflightStatus.OK,
                              "chromium installed", detail={"executable_path": path})
    except Exception as e:
        return PreflightCheck("browser", PreflightStatus.DOWN,
                              f"chromium not installed — run: playwright install chromium ({e})")


def check_ollama() -> PreflightCheck:
    """Cheap HTTP ping to the Ollama server. If Ollama isn't running,
    the local `phi3` verifier + embeddings + intent classification all
    fall back — degraded, not down."""
    from backend.server.config import settings
    try:
        import httpx
        with httpx.Client(timeout=2.0) as client:
            r = client.get(f"{settings.ollama_url.rstrip('/')}/api/tags")
        if r.status_code == 200:
            models = [m.get("name") for m in r.json().get("models", [])]
            return PreflightCheck("ollama", PreflightStatus.OK,
                                  f"reachable ({len(models)} models installed)",
                                  detail={"models": models})
        return PreflightCheck("ollama", PreflightStatus.DEGRADED,
                              f"reachable but returned {r.status_code}")
    except Exception as e:
        return PreflightCheck("ollama", PreflightStatus.DEGRADED,
                              f"unreachable — verifier/embeddings will fall back: {e}")


def check_llm_providers() -> list[PreflightCheck]:
    """Verify each configured cloud LLM provider is registered. Does NOT
    make a billable API call — that would burn quota on every boot."""
    from backend.server.config import settings
    checks: list[PreflightCheck] = []

    # Gemini
    if settings.gemini_api_key:
        try:
            from backend.ai_modules.llm import get_provider
            p = get_provider()
            if "gemini" in p._backends:
                checks.append(PreflightCheck("llm:gemini", PreflightStatus.OK,
                                             "registered", detail={"model": settings.gemini_model}))
            else:
                checks.append(PreflightCheck("llm:gemini", PreflightStatus.DOWN,
                                             "key set but backend not registered"))
        except Exception as e:
            checks.append(PreflightCheck("llm:gemini", PreflightStatus.DOWN,
                                         f"provider init failed: {e}"))
    else:
        checks.append(PreflightCheck("llm:gemini", PreflightStatus.DISABLED,
                                     "GEMINI_API_KEY not set"))

    # Ollama Cloud — hosted reasoning models (planner, coding, chat)
    if settings.ollama_api_key:
        try:
            from backend.ai_modules.llm import get_provider
            p = get_provider()
            if "ollama_cloud" in p._backends:
                checks.append(PreflightCheck("llm:ollama_cloud", PreflightStatus.OK,
                                             "registered", detail={
                                                 "model": settings.ollama_cloud_model,
                                                 "base_url": settings.ollama_cloud_url,
                                             }))
            else:
                checks.append(PreflightCheck("llm:ollama_cloud", PreflightStatus.DOWN,
                                             "key set but backend not registered"))
        except Exception as e:
            checks.append(PreflightCheck("llm:ollama_cloud", PreflightStatus.DOWN,
                                         f"provider init failed: {e}"))
    else:
        checks.append(PreflightCheck("llm:ollama_cloud", PreflightStatus.DISABLED,
                                     "OLLAMA_API_KEY not set"))

    # Fallback backend check — if configured, it must be registered.
    fb = (settings.llm_fallback_backend or "").strip()
    if fb:
        try:
            from backend.ai_modules.llm import get_provider
            p = get_provider()
            if fb in p._backends:
                checks.append(PreflightCheck("llm:fallback", PreflightStatus.OK,
                                             f"'{fb}' registered as fallback"))
            else:
                checks.append(PreflightCheck("llm:fallback", PreflightStatus.DOWN,
                                             f"llm_fallback_backend='{fb}' NOT registered"))
        except Exception as e:
            checks.append(PreflightCheck("llm:fallback", PreflightStatus.DOWN,
                                         f"could not verify fallback: {e}"))

    return checks


# ── Aggregate runner ─────────────────────────────────────────────────────

def run_preflight() -> list[PreflightCheck]:
    """Run every preflight check. Individual failures never bubble.

    Ordering matters for the boot log — services first (fastest, tells you
    if the app booted at all), then the ws_bridge (Phase 3 catch), then
    the outbound-dependency checks (browser / ollama / LLM providers).
    """
    # Dict-of-callables so a mock/patch swap keeps the stable name.
    # An earlier list-of-fns lookup relied on fn.__name__ which
    # MagicMock doesn't carry, producing "unknown_check" when patched.
    registry: dict[str, callable] = {
        "check_services":       check_services,
        "check_ws_bridge":      check_ws_bridge,
        "check_browser":        check_browser,
        "check_ollama":         check_ollama,
        "check_llm_providers":  check_llm_providers,
    }
    checks: list[PreflightCheck] = []
    for name, fn in registry.items():
        try:
            r = fn()
            if isinstance(r, list):
                checks.extend(r)
            else:
                checks.append(r)
        except Exception as e:
            # Should not happen — each check catches its own exceptions.
            # Last line of defence so preflight itself never crashes the
            # boot log or the diagnostics endpoint.
            checks.append(PreflightCheck(name, PreflightStatus.DOWN,
                                         f"preflight check crashed: {e}"))
    return checks


def summary(checks: list[PreflightCheck]) -> dict[str, int]:
    """Roll checks up to counts per status. For quick logging."""
    counts = {s.value: 0 for s in PreflightStatus}
    for c in checks:
        counts[c.status.value] += 1
    return counts


def log_preflight(checks: list[PreflightCheck]) -> None:
    """One-line-per-check readable log for boot. DOWN loud, OK quiet."""
    counts = summary(checks)
    log.info("Preflight: %s", " ".join(f"{k}={v}" for k, v in counts.items() if v))
    for c in checks:
        if c.status in (PreflightStatus.DOWN, PreflightStatus.DEGRADED):
            log.warning("  [%s] %s: %s", c.status.value.upper(), c.name, c.message)
        else:
            log.debug("  [%s] %s: %s", c.status.value, c.name, c.message)
