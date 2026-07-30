"""SG_CUBE backend package.

Importing this package makes log output encoding-safe. That is the only side
effect: no handlers are added, no levels are set, no format is imposed.

Why it lives here rather than in an entry point: on Windows, sys.stdout defaults
to the console codepage (cp1252 on this machine). Any log record carrying a
character outside that codepage — "→" from the Planner's reasoning string is the
one that bit us — raises UnicodeEncodeError *inside the logging handler*. The
record is dropped and the original exception it was reporting is lost:

    log.exception(f"trigger crash: {e}")
    --> UnicodeEncodeError: 'charmap' codec can't encode character '\\u2192'

So the bug destroys the evidence for whatever bug it was reporting, and it does
so from every entry point — uvicorn, the daemon CLI, pytest, ad-hoc probe
scripts. Fixing it in `backend/server/main.py` would leave the scripts broken,
which is exactly where debugging happens.

reconfigure() mutates the existing TextIOWrapper in place, so handlers that
already captured a reference to sys.stdout (uvicorn installs its own) are fixed
too. errors="backslashreplace" is the load-bearing half: it guarantees a write
can never raise even if the terminal cannot render the character.
"""
import sys


def _make_log_streams_encoding_safe() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue  # replaced by a plain object (pytest capture, some hosts)
        try:
            reconfigure(encoding="utf-8", errors="backslashreplace")
        except (ValueError, OSError):
            # Detached or already-closed stream — nothing to fix, and this must
            # never be the reason an import fails.
            pass


_make_log_streams_encoding_safe()
