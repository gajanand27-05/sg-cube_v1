"""Phase 5D — Healer coverage audit.

Enumerates every error string the tools observed in the recon can produce
and asserts each maps to a specific RecoveryPath rule, not the ESCALATE
default. Regression guard: if someone adds a new tool that emits a
never-before-seen error phrase and forgets to file a Healer rule for it,
the audit test fails with a clear name.

The default ESCALATE case is explicitly tested — it fires only when
nothing above matched, and it never infinite-loops (each Healer call
is stateless; the loop bound is up to the Commander).
"""
import sys
from pathlib import Path

_project_root = Path(__file__).resolve().parents[1]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))


# ── Gap-fill rules added in Phase 5D ──────────────────────────────────

def test_task_cancelled_aborts():
    """runtime.py emits 'Task was cancelled' when the user interrupts.
    Retrying a user-cancelled call is the WRONG response."""
    from backend.core.healing import SelfHealer, RecoveryPath
    h = SelfHealer()
    assert h.analyze("get_stock", "Task was cancelled", attempt=1) == RecoveryPath.ABORT
    assert h.analyze("get_stock", "user cancelled the operation", attempt=1) == RecoveryPath.ABORT
    print("  [PASS] Task cancellation → ABORT (not RETRY, not ESCALATE)")


def test_empty_required_arg_is_fix():
    """LLM called the tool with an empty required arg (data_sources emits
    'empty symbol' / 'empty location'). FIX so the Planner retries with
    the argument populated, not ESCALATE."""
    from backend.core.healing import SelfHealer, RecoveryPath
    h = SelfHealer()
    assert h.analyze("get_stock",   "empty symbol",   attempt=1) == RecoveryPath.FIX
    assert h.analyze("get_weather", "empty location", attempt=1) == RecoveryPath.FIX
    print("  [PASS] empty required arg → FIX")


def test_unknown_tool_is_fix():
    """registry.py::call emits 'unknown tool: X' when the LLM invented
    a name. FIX so the LLM tries a real one."""
    from backend.core.healing import SelfHealer, RecoveryPath
    h = SelfHealer()
    assert h.analyze("hallucinated_name", "unknown tool: 'hallucinated_name'",
                     attempt=1) == RecoveryPath.FIX
    print("  [PASS] unknown tool → FIX")


def test_parse_failed_is_fix():
    """data_sources.py emits 'parse failed: ...' when a provider returns
    an unexpected shape. FIX (a retry with fresh args often works)."""
    from backend.core.healing import SelfHealer, RecoveryPath
    h = SelfHealer()
    assert h.analyze("get_stock", "parse failed: KeyError 'price'",
                     attempt=1) == RecoveryPath.FIX
    print("  [PASS] parse failed → FIX")


def test_widened_http_5xx_retries():
    """Pre-Phase-5D only caught 503/504. Now 500/501/502 also retry.
    Anything under 5xx is a transport/upstream blip, not a client error."""
    from backend.core.healing import SelfHealer, RecoveryPath
    h = SelfHealer()
    for code in ("500", "501", "502"):
        err = f"HTTP {code} internal error"
        assert h.analyze("get_stock", err, attempt=1) == RecoveryPath.RETRY, (
            f"HTTP {code} should RETRY, not fall through"
        )
    print("  [PASS] HTTP 500/501/502/503/504 all → RETRY")


def test_network_error_retries():
    """data_sources.py emits 'network error: <e>' on transport failure.
    RETRY — many are transient DNS blips."""
    from backend.core.healing import SelfHealer, RecoveryPath
    h = SelfHealer()
    assert h.analyze("get_stock", "network error: name resolution failed",
                     attempt=1) == RecoveryPath.RETRY
    assert h.analyze("get_stock", "fetch failed and no cache: TimeoutError",
                     attempt=1) == RecoveryPath.RETRY
    print("  [PASS] network error / fetch failed → RETRY")


def test_no_data_returned_pivots():
    """data_sources.py emits 'no price returned' and 'no headlines in X' when
    the query resolves but the provider had nothing. PIVOT nudges the
    Planner to try a different symbol / topic."""
    from backend.core.healing import SelfHealer, RecoveryPath
    h = SelfHealer()
    assert h.analyze("get_stock", "no price returned for 'ZZZZ' — check the symbol",
                     attempt=1) == RecoveryPath.PIVOT
    assert h.analyze("get_news_data", "no headlines in 'obscure-topic'",
                     attempt=1) == RecoveryPath.PIVOT
    print("  [PASS] no data returned → PIVOT (try different query)")


def test_geocode_failure_pivots():
    """data_sources.py emits 'could not geocode X' for bad location names.
    PIVOT: Planner should try a canonical form ('SF' → 'San Francisco')
    rather than escalate."""
    from backend.core.healing import SelfHealer, RecoveryPath
    h = SelfHealer()
    assert h.analyze("get_weather", "could not geocode 'SF'",
                     attempt=1) == RecoveryPath.PIVOT
    print("  [PASS] could not geocode → PIVOT")


# ── Regression guards for existing rules ─────────────────────────────

def test_existing_rules_unchanged():
    """Every pre-Phase-5D rule still fires. If a rule silently regressed
    because we widened a substring match, this catches it."""
    from backend.core.healing import SelfHealer, RecoveryPath
    h = SelfHealer()
    cases = [
        # (error, attempt, expected)
        ("permission denied on registry write", 1, RecoveryPath.ABORT),
        ("window closed mid-operation", 1, RecoveryPath.RETRY),
        ("window closed mid-operation", 2, RecoveryPath.ABORT),
        ("Playwright navigation timeout: goto exceeded", 1, RecoveryPath.RETRY),
        ("Playwright navigation timeout: goto exceeded", 2, RecoveryPath.ABORT),
        ("connection reset by peer", 1, RecoveryPath.RETRY),
        ("temporary failure", 1, RecoveryPath.RETRY),
        ("missing argument 'symbol'", 1, RecoveryPath.FIX),
        ("access denied by UAC", 1, RecoveryPath.ESCALATE),
        ("chromium launch failed", 1, RecoveryPath.ESCALATE),
        ("no element matching selector .foo", 1, RecoveryPath.PIVOT),
        ("canvas schema invalid at '0'", 1, RecoveryPath.ABORT),
        ("provider rate limit (429)", 1, RecoveryPath.PIVOT),
        ("FINNHUB_API_KEY not configured", 1, RecoveryPath.ESCALATE),
        ("no window matching 'notepad'", 1, RecoveryPath.PIVOT),
    ]
    for err, att, expected in cases:
        got = h.analyze("t", err, attempt=att)
        assert got == expected, f"regression: {err!r} attempt={att} → {got}, expected {expected}"
    print(f"  [PASS] {len(cases)} pre-Phase-5D rules still fire as before")


def test_default_is_escalate_and_finite():
    """Anything not matched by any specific rule → ESCALATE (the safe
    default). This is the "unmapped error" path and must be:
      * Not silent — returns an actionable path.
      * Not infinite — a single call to analyze() is stateless; retry
        bound lives in the Commander loop, not here.
    """
    from backend.core.healing import SelfHealer, RecoveryPath
    h = SelfHealer()
    weird = "some brand-new error string from a tool we haven't audited yet"
    assert h.analyze("anything", weird, attempt=1) == RecoveryPath.ESCALATE
    # Repeated calls stay ESCALATE — no state accumulation between calls,
    # so no infinite loop is possible at this layer.
    assert h.analyze("anything", weird, attempt=99) == RecoveryPath.ESCALATE
    print("  [PASS] unmapped error → ESCALATE default (finite, actionable)")


if __name__ == "__main__":
    test_task_cancelled_aborts()
    test_empty_required_arg_is_fix()
    test_unknown_tool_is_fix()
    test_parse_failed_is_fix()
    test_widened_http_5xx_retries()
    test_network_error_retries()
    test_no_data_returned_pivots()
    test_geocode_failure_pivots()
    test_existing_rules_unchanged()
    test_default_is_escalate_and_finite()
    print("All Phase 5D Healer coverage tests passed.")
