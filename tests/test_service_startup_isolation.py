"""Phase 0 Part A — start_services fault isolation.

If any one background service raises during start, the server must still boot,
the other services must still start, the failed one must report "failed" with
its error captured, and a service with ENABLE_*=false must report "disabled"
(never "failed").
"""
import sys
from pathlib import Path

_project_root = Path(__file__).resolve().parents[1]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))


class _MockOk:
    """Stand-in for a well-behaved daemon service."""
    def __init__(self):
        self.started = False
        self.stopped = False
    def start(self):
        self.started = True
    def stop(self):
        self.stopped = True


class _MockFail:
    """Stand-in for a service that blows up on start."""
    def __init__(self, msg="simulated boot failure"):
        self.msg = msg
    def start(self):
        raise RuntimeError(self.msg)
    def stop(self):
        pass


class _FakeSettings:
    """Minimal settings shape start_services reads. All flags on so we
    exercise every branch (except wake_word, which is off to avoid needing
    the Vosk model on the CI box)."""
    enable_clipboard = True
    enable_vision = True
    enable_watcher = True
    enable_telemetry = True
    enable_wake_word = False
    wake_phrase = "onyx"
    wake_capture_seconds = 2.5
    wake_device = None


def _swap_service_globals(**replacements):
    """Replace the module-level singletons start_services imports.
    Returns a rollback callable that restores originals."""
    import backend.daemon.clipboard_watcher as cw_mod
    import backend.daemon.vision_loop as vl_mod
    import backend.daemon.telemetry as tel_mod
    import backend.core.agents.watcher as wa_mod

    originals = {
        "clipboard": (cw_mod, "watcher", cw_mod.watcher),
        "vision":    (vl_mod, "vision_loop", vl_mod.vision_loop),
        "telemetry": (tel_mod, "telemetry_loop", tel_mod.telemetry_loop),
        "watcher":   (wa_mod, "watcher", wa_mod.watcher),
    }

    for name, mock in replacements.items():
        mod, attr, _ = originals[name]
        setattr(mod, attr, mock)

    def rollback():
        for _, (mod, attr, original) in originals.items():
            setattr(mod, attr, original)

    return rollback


def test_failing_service_does_not_stop_others():
    """A raise inside one service's start() must not prevent the others from starting."""
    from backend.daemon import main as dm

    ok_vision = _MockOk()
    ok_watcher = _MockOk()
    ok_telemetry = _MockOk()
    fail_clipboard = _MockFail("clipboard failed to start")

    rollback = _swap_service_globals(
        clipboard=fail_clipboard,
        vision=ok_vision,
        watcher=ok_watcher,
        telemetry=ok_telemetry,
    )
    try:
        handle = dm.start_services(_FakeSettings())
        status = dm.get_service_status()

        # The failing service reports failed + captured error message
        assert status["clipboard"]["status"] == "failed", status["clipboard"]
        assert "clipboard failed to start" in (status["clipboard"]["error"] or "")

        # All the others reached started state despite one failure above them
        assert status["vision"]["status"]    == "started", status["vision"]
        assert status["watcher"]["status"]   == "started", status["watcher"]
        assert status["telemetry"]["status"] == "started", status["telemetry"]

        # And their start() actually ran
        assert ok_vision.started is True
        assert ok_watcher.started is True
        assert ok_telemetry.started is True

        # Wake word was off, so it's disabled — never "failed"
        assert status["wake_word"]["status"] == "disabled"
        assert status["wake_word"]["error"] is None

        # Handle came back cleanly — no wake-word listener since it was disabled
        assert handle["listener"] is None
        assert handle["listener_thread"] is None

        # stop_services on a partial handle must not crash
        dm.stop_services(handle)

        print("  [PASS] fault-isolation: failing service kept the rest alive")
    finally:
        rollback()


def test_disabled_never_reports_failed():
    """A service with ENABLE_*=false is 'disabled' — must never be 'failed'."""
    from backend.daemon import main as dm

    ok = _MockOk()
    rollback = _swap_service_globals(clipboard=ok, vision=ok, watcher=ok, telemetry=ok)

    class AllDisabled(_FakeSettings):
        enable_clipboard = False
        enable_vision = False
        enable_watcher = False
        enable_telemetry = False
        enable_wake_word = False

    try:
        dm.start_services(AllDisabled())
        status = dm.get_service_status()

        for name in ("clipboard", "vision", "watcher", "telemetry", "wake_word"):
            assert status[name]["status"] == "disabled", (name, status[name])
            assert status[name]["error"] is None, (name, status[name])
            assert status[name]["started_at"] is None, (name, status[name])

        print("  [PASS] disabled services never leak as 'failed'")
    finally:
        rollback()


def test_all_services_start_when_all_succeed():
    """Sanity: on the happy path every service reports 'started'."""
    from backend.daemon import main as dm

    ok = {"clipboard": _MockOk(), "vision": _MockOk(), "watcher": _MockOk(), "telemetry": _MockOk()}
    rollback = _swap_service_globals(**ok)
    try:
        dm.start_services(_FakeSettings())
        status = dm.get_service_status()

        for name in ("clipboard", "vision", "watcher", "telemetry"):
            assert status[name]["status"] == "started", (name, status[name])
            assert status[name]["error"] is None
            assert status[name]["started_at"] is not None

        assert status["wake_word"]["status"] == "disabled"
        print("  [PASS] happy path: all enabled services report 'started'")
    finally:
        rollback()


if __name__ == "__main__":
    test_failing_service_does_not_stop_others()
    test_disabled_never_reports_failed()
    test_all_services_start_when_all_succeed()
    print("All service-startup isolation tests passed.")
