"""Phase 5C — startup preflight.

Every check must:
  * Return a PreflightCheck (or list), never raise.
  * Report OK / DEGRADED / DOWN / DISABLED honestly based on real state.
  * Be idempotent — safe to call from boot AND from the diagnostics endpoint.

The load-bearing check is `check_ws_bridge`: this is the specific catch
that would have surfaced the Phase 3 dead-bridge bug at boot instead of
at manual-test time.
"""
import sys
from pathlib import Path
from unittest.mock import patch

_project_root = Path(__file__).resolve().parents[1]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))


# ── run_preflight never raises ────────────────────────────────────────

def test_run_preflight_returns_list_never_raises():
    """Whatever the state, preflight returns a list of PreflightCheck.
    A crashy check must be caught and reported, not bubble."""
    from backend.core.preflight import run_preflight, PreflightCheck
    checks = run_preflight()
    assert isinstance(checks, list)
    assert all(isinstance(c, PreflightCheck) for c in checks)
    assert len(checks) > 0, "expected at least one check to run"
    print(f"  [PASS] run_preflight returned {len(checks)} checks, no exception")


def test_run_preflight_survives_a_broken_check():
    """If check_services suddenly raises an unexpected exception,
    run_preflight must still return other results."""
    from backend.core import preflight as p
    def _boom():
        raise RuntimeError("broken check")

    with patch.object(p, "check_services", side_effect=_boom):
        checks = p.run_preflight()
    # We expect a synthesized DOWN entry for the broken check + the
    # remaining checks.
    names = [c.name for c in checks]
    assert "check_services" in names, f"expected a synthetic entry for the crashed check, got {names}"
    broken = next(c for c in checks if c.name == "check_services")
    assert broken.status.value == "down"
    assert "broken check" in broken.message
    # At least one other check must have still run
    assert len(checks) > 1, "run_preflight should have run the other checks"
    print("  [PASS] a broken check is reported DOWN, other checks still run")


# ── Individual checks ─────────────────────────────────────────────────

def test_check_ws_bridge_reports_ok_when_setup_ran():
    """The load-bearing Phase 3 catch. After connect() has ever run
    (or this check itself), _bridge_setup must be True."""
    from backend.core.preflight import check_ws_bridge, PreflightStatus
    from backend.server.ws_ui import get_manager
    # Reset the singleton flag to simulate a fresh boot
    mgr = get_manager()
    mgr._bridge_setup = False
    result = check_ws_bridge()
    assert result.name == "ws_bridge"
    assert result.status == PreflightStatus.OK, f"expected OK, got {result.status}: {result.message}"
    assert mgr._bridge_setup, "check should have primed the bridge"
    print("  [PASS] ws_bridge: primes _setup_event_bridge() and reports OK")


def test_check_ws_bridge_reports_down_if_setup_raises():
    """If _setup_event_bridge somehow raises, we report DOWN with the
    exception — do NOT bubble. This is the diagnostic value: never a
    silent failure."""
    from backend.core.preflight import check_ws_bridge, PreflightStatus
    from backend.server.ws_ui import get_manager
    mgr = get_manager()
    with patch.object(mgr, "_setup_event_bridge", side_effect=RuntimeError("bus down")):
        # Force flag off so the check tries to set up
        mgr._bridge_setup = False
        result = check_ws_bridge()
    # Restore
    mgr._bridge_setup = False
    assert result.status == PreflightStatus.DOWN
    assert "bus down" in result.message
    print("  [PASS] ws_bridge: bridge setup exception reported as DOWN")


def test_check_services_maps_status_correctly():
    """Reads backend.daemon.main.get_service_status and maps each
    entry's status to OK / DISABLED / DOWN."""
    from backend.core import preflight as p
    from backend.core.preflight import PreflightStatus

    fake_status = {
        "clipboard": {"status": "started", "error": None, "started_at": "2026-07-09T00:00:00"},
        "vision":    {"status": "disabled", "error": None, "started_at": None},
        "wake_word": {"status": "failed",   "error": "no mic", "started_at": None},
    }
    with patch("backend.daemon.main.get_service_status", return_value=fake_status):
        checks = p.check_services()

    by_name = {c.name: c for c in checks}
    assert by_name["service:clipboard"].status == PreflightStatus.OK
    assert by_name["service:vision"].status == PreflightStatus.DISABLED
    assert by_name["service:wake_word"].status == PreflightStatus.DOWN
    assert "no mic" in by_name["service:wake_word"].message
    print("  [PASS] check_services maps started/disabled/failed → OK/DISABLED/DOWN")


def test_check_ollama_reports_degraded_when_unreachable():
    """Ollama unreachable is DEGRADED not DOWN — the verifier + embeddings
    have local fallbacks, so the app still works, just less well."""
    from backend.core.preflight import check_ollama, PreflightStatus
    import httpx
    class _BadClient:
        def __init__(self, *a, **kw): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def get(self, url):
            raise httpx.ConnectError("nothing at that port")

    with patch("httpx.Client", _BadClient):
        result = check_ollama()
    assert result.status == PreflightStatus.DEGRADED
    assert "unreachable" in result.message.lower()
    print("  [PASS] check_ollama: unreachable → DEGRADED (not DOWN)")


# ── Summary helper ────────────────────────────────────────────────────

def test_summary_counts_per_status():
    from backend.core.preflight import PreflightCheck, PreflightStatus, summary
    checks = [
        PreflightCheck("a", PreflightStatus.OK, ""),
        PreflightCheck("b", PreflightStatus.OK, ""),
        PreflightCheck("c", PreflightStatus.DEGRADED, ""),
        PreflightCheck("d", PreflightStatus.DOWN, ""),
        PreflightCheck("e", PreflightStatus.DISABLED, ""),
    ]
    counts = summary(checks)
    assert counts["ok"] == 2
    assert counts["degraded"] == 1
    assert counts["down"] == 1
    assert counts["disabled"] == 1
    print("  [PASS] summary counts checks per status")


if __name__ == "__main__":
    test_run_preflight_returns_list_never_raises()
    test_run_preflight_survives_a_broken_check()
    test_check_ws_bridge_reports_ok_when_setup_ran()
    test_check_ws_bridge_reports_down_if_setup_raises()
    test_check_services_maps_status_correctly()
    test_check_ollama_reports_degraded_when_unreachable()
    test_summary_counts_per_status()
    print("All Phase 5C preflight tests passed.")
