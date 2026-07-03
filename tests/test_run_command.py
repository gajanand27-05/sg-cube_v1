"""Smoke check for the T2-1 run_command tool."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import backend.core.tools  # noqa: F401  triggers discovery
from backend.core.tools.registry import REGISTRY


def _checks():
    assert "run_command" in REGISTRY, "run_command missing from REGISTRY"
    t = REGISTRY["run_command"]
    assert t.security.value == "caution", f"expected CAUTION, got {t.security}"

    r = t.func(command="echo hello-sg-cube")
    assert r.status.value == "success", r.message
    assert "hello-sg-cube" in (r.message or "")
    print("  PASS: echo round-trip")

    r2 = t.func(command='python -c "print(2+2)"')
    assert r2.status.value == "success"
    assert "4" in (r2.message or "")
    print("  PASS: python inline invocation")

    r3 = t.func(command="nonexistent_cmd_xyz_123")
    assert r3.status.value == "error", r3.message
    print("  PASS: non-zero exit reported as error")

    r4 = t.func(command="   ")
    assert r4.status.value == "blocked"
    print("  PASS: empty command blocked")

    r5 = t.func(command='python -c "import time; time.sleep(5)"', timeout_seconds=1)
    assert r5.status.value == "error"
    assert "timed out" in (r5.message or r5.reason or "")
    print("  PASS: timeout aborts long-running command")


_checks()
print("=== T2-1 verification: ALL PASSED ===")
