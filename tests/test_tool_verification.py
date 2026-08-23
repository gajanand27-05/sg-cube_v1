"""Tool post-condition verification.

A side-effecting tool may only report success it observed. See
docs/superpowers/specs/2026-08-23-tool-verification-design.md.

Vocabulary note: the outcomes are confirmed / unconfirmed / contradicted.
"verified" is NOT used — AgentCompletedEvent.status already spends that word
on Guardian's pre-execution plan approval, on both sides of the py/ts boundary.
"""
import sys
from pathlib import Path

_project_root = Path(__file__).resolve().parents[1]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))


def test_tool_records_a_declared_verify():
    from backend.core.tools.registry import (
        REGISTRY, CapabilityTier, tool,
    )

    def _check(args, result):
        return None

    @tool(tier=CapabilityTier.SYSTEM_WRITE, trusted=True, verify=_check)
    def _fake_verified_tool(level: int) -> dict:
        """Fake tool for the registration test."""
        return {"status": "success", "message": "ok"}

    try:
        assert REGISTRY["_fake_verified_tool"].verify is _check
    finally:
        REGISTRY.pop("_fake_verified_tool", None)


def test_tool_without_verify_declares_none():
    """A tool that declares no post-condition is not an error — it is
    unconfirmed, which is a different thing and is decided at call time."""
    from backend.core.tools.registry import REGISTRY, CapabilityTier, tool

    @tool(tier=CapabilityTier.SYSTEM_WRITE, trusted=True)
    def _fake_unverified_tool() -> dict:
        """Fake tool for the registration test."""
        return {"status": "success", "message": "ok"}

    try:
        assert REGISTRY["_fake_unverified_tool"].verify is None
    finally:
        REGISTRY.pop("_fake_unverified_tool", None)


if __name__ == "__main__":
    for _name, _fn in sorted(globals().items()):
        if _name.startswith("test_") and callable(_fn):
            _fn()
            print(f"  [PASS] {_name}")
