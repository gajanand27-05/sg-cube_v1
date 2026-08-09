"""The dogfooding ledger's resettable measurement window.

Lifetime counters run from the first ever launch and blend every era the
assistant has been through, so they cannot answer "how is the build I am
running now behaving" — which is exactly what the three data-gated tickets
need. These tests pin the property that makes the window worth having: it
measures the present without destroying the history.
"""
import json

from backend.core.dogfooding import Ledger


def _ledger(tmp_path):
    return Ledger(path=tmp_path / "dogfooding.json")


def test_counters_land_in_both_lifetime_and_window(tmp_path):
    led = _ledger(tmp_path)
    led.record_command(True, latency_ms=100)
    led.record_command(False, latency_ms=300)
    snap = led.snapshot()
    assert snap["command_total"] == 2
    assert snap["window"]["command_total"] == 2
    assert snap["rates"]["command_success_pct"] == 50.0
    assert snap["window_rates"]["command_success_pct"] == 50.0


def test_reset_zeroes_the_window_and_keeps_the_history(tmp_path):
    """The whole point. If reset dropped lifetime totals it would destroy real
    history; if it left the window alone it would answer the wrong question."""
    led = _ledger(tmp_path)
    for _ in range(8):
        led.record_command(False, latency_ms=40_000)   # a bad old era
    led.record_crash()

    led.reset_window(label="abc1234")
    led.record_command(True, latency_ms=900)           # the build under test

    snap = led.snapshot()
    assert snap["command_total"] == 9, "lifetime history was destroyed"
    assert snap["window"]["command_total"] == 1
    # Lifetime says 11% and 40s; the window tells the truth about now.
    assert snap["rates"]["command_success_pct"] == 11.11
    assert snap["window_rates"]["command_success_pct"] == 100.0
    assert snap["rates"]["avg_command_latency_ms"] > 30_000
    assert snap["window_rates"]["avg_command_latency_ms"] == 900
    assert snap["window"]["crashes"] == 0, "a pre-reset crash leaked into the window"
    assert snap["crashes"] == 1
    assert snap["window_rates"]["label"] == "abc1234"


def test_an_existing_ledger_does_not_backfill_the_window(tmp_path):
    """Opening a ledger written before windows existed must START a window,
    not import the lifetime totals into it — importing is precisely the
    history the window exists to exclude."""
    path = tmp_path / "dogfooding.json"
    path.write_text(json.dumps({
        "started_at": "2026-07-02T09:37:01+00:00",
        "wake_attempts": 2138, "wake_successes": 77,
        "command_total": 2138, "command_success": 77, "crashes": 588,
        "total_command_latency_ms": 83_342_726,
    }), encoding="utf-8")

    snap = Ledger(path=path).snapshot()
    assert snap["wake_attempts"] == 2138           # history preserved
    assert snap["window"]["wake_attempts"] == 0    # window starts clean
    assert snap["window_rates"]["wake_success_pct"] is None
    assert snap["window"]["started_at"]


def test_no_data_reads_as_none_not_zero(tmp_path):
    """0% means actively broken; None means nothing measured. Conflating them
    is how you 'fix' a problem that was never observed."""
    snap = _ledger(tmp_path).snapshot()
    assert snap["window_rates"]["command_success_pct"] is None
    assert snap["window_rates"]["avg_command_latency_ms"] is None


def test_window_survives_a_reopen(tmp_path):
    path = tmp_path / "dogfooding.json"
    led = Ledger(path=path)
    led.reset_window(label="run-1")
    led.record_wake(True)

    reopened = Ledger(path=path).snapshot()
    assert reopened["window"]["wake_attempts"] == 1
    assert reopened["window_rates"]["label"] == "run-1"
