"""Log output must never raise on a non-cp1252 character — see T-log-cp1252.

The Planner's reasoning strings contain "→". On Windows, sys.stdout defaults to
the console codepage, so logging such a record raised UnicodeEncodeError inside
the handler: the record was dropped and the original exception it was reporting
was lost. `log.exception(f"trigger crash: {e}")` in trigger.py reported nothing
but the encoding error.

Run in subprocesses because the fix reconfigures sys.stdout at import, and
pytest has already replaced it in-process. Each test includes the control case,
so a regression can't pass silently by the test losing its own teeth.
"""
import subprocess
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]

ARROW = "→"

_LOG_AN_ARROW = """
import logging, sys
{importline}
logging.basicConfig(level=logging.INFO, stream=sys.stdout)
try:
    raise RuntimeError("plan: open chrome \\u2192 get_time")
except Exception as e:
    logging.getLogger("t").exception("trigger crash: %s", e)
print("REACHED_END")
"""


def _run(importline: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-c", _LOG_AN_ARROW.format(importline=importline)],
        cwd=str(_PROJECT_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        # cp1252 is what the failure needs. Without forcing it the test would
        # pass on any machine whose console already speaks UTF-8.
        env={**_env(), "PYTHONIOENCODING": "cp1252"},
        timeout=120,
    )


def _env() -> dict:
    import os
    return dict(os.environ)


def test_importing_backend_makes_arrow_logging_safe():
    result = _run("import backend")
    combined = result.stdout + result.stderr

    assert "UnicodeEncodeError" not in combined, (
        f"logging an arrow still raises:\n{combined}"
    )
    assert "REACHED_END" in result.stdout
    # The point is the *original* error survives, not merely that nothing threw.
    assert "plan: open chrome" in combined


def test_control_without_the_fix_actually_fails():
    """Proves the test above is measuring something. Without importing backend,
    cp1252 stdout must still blow up on the arrow — if this ever stops failing,
    the environment changed and the test above proves nothing."""
    result = _run("pass")
    combined = result.stdout + result.stderr

    assert "UnicodeEncodeError" in combined, (
        "expected cp1252 stdout to reject the arrow without the fix; "
        f"got:\n{combined}"
    )


def test_helper_tolerates_streams_without_reconfigure():
    """pytest capture and some hosts replace sys.stdout with a plain object."""
    import backend

    class _NoReconfigure:
        pass

    real_out, real_err = sys.stdout, sys.stderr
    sys.stdout = sys.stderr = _NoReconfigure()
    try:
        backend._make_log_streams_encoding_safe()  # must not raise
    finally:
        sys.stdout, sys.stderr = real_out, real_err


def test_helper_tolerates_a_stream_that_refuses():
    import backend

    class _Refuses:
        def reconfigure(self, **kw):
            raise ValueError("detached")

    real_out, real_err = sys.stdout, sys.stderr
    sys.stdout = sys.stderr = _Refuses()
    try:
        backend._make_log_streams_encoding_safe()  # must not raise
    finally:
        sys.stdout, sys.stderr = real_out, real_err
