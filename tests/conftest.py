"""Keep the test suite out of the real dogfooding ledger.

`backend/database/dogfooding.json` is a PRODUCTION data file. It is the thing
the data-gated tickets (T-barge-in-tuning, T-latency-optimization,
T-tool-surface-pruning) are supposed to be read from, and it is persistent by
design so a day of real use survives restarts.

Several tests exercise the real recording sites — `on_barge_in` writes a
barge-in, and anything that drives `WakeWordListener.listen()` writes a wake
attempt through `_start_turn`. Those calls went straight into the production
file. Caught when a freshly started backend reported `barge_in_self_pct: 0.0`
after a barge-in that never happened: the count came from `pytest`.

The damage is not cosmetic. It inflates wake_attempts against a real
wake_successes, so the measured wake success rate reads LOWER than it is, and
the whole point of the window is to hand back a number you can trust. A
suite that writes to it makes every reading suspect and, worse, plausible.

Redirected for the entire session rather than per-test, because the ledger is
a module-level singleton read at import time by trigger.py and wake_word.py —
patching it in individual tests means the next person to add a test that
touches a recording site silently reintroduces this.

Redirected by mutating the singleton IN PLACE rather than rebinding names.
`trigger.py` and `wake_word.py` do `from ... import ledger as
dogfooding_ledger`, so they hold the object, not the module attribute — and a
module not yet imported when this fixture runs would pick up the real one
later. Same object with a different path covers every holder, past and future.
"""
import os
import sys
import tempfile
from pathlib import Path

import pytest

_project_root = Path(__file__).resolve().parents[1]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

# Every piece of mutable state — Chroma memory, the ledger, captures, contacts,
# logs — resolves through backend/core/paths.py, which reads SG_CUBE_HOME once
# at import. Set here, before any test module imports backend, so the whole
# suite writes to a throwaway directory. The per-singleton fixtures below
# predate this and stay as a second guard; this one also covers the stores
# they never reached (a suite run wrote the real chroma_db and
# ollama_restarts.jsonl). Models are not state and still resolve to the
# checkout, so real-audio tests keep their Vosk model.
os.environ["SG_CUBE_HOME"] = tempfile.mkdtemp(prefix="sg_cube_test_home_")


@pytest.fixture(autouse=True, scope="session")
def _isolate_dogfooding_ledger(tmp_path_factory):
    """Point the singleton ledger at a throwaway file for the whole run."""
    from backend.core import dogfooding

    tmp = tmp_path_factory.mktemp("dogfooding") / "dogfooding.json"
    led = dogfooding.ledger

    real_path = led._path
    real_data = led._data
    led._path = tmp
    # Fresh counters as well as a fresh file: leaving the loaded production
    # numbers in memory would let a test read them and assert against whatever
    # happened to be on this machine.
    led._data = {}
    led.__init__(path=tmp)  # re-runs the defaulting, binds the temp path
    try:
        yield led
    finally:
        led._path = real_path
        led._data = real_data


@pytest.fixture(autouse=True, scope="session")
def _isolate_capture_archive(tmp_path_factory):
    """Keep the suite out of the real capture archive.

    Same hazard as the two below, and it bites hardest here. Several tests
    drive the REAL listen loop (test_barge_in_real_audio, test_wake_preroll),
    and the wake branch archives the pre-roll that fired it — reaching the
    module-level `_ARCHIVE_DIR`, not a fixture. Measured: three test files
    added three wake records to backend/database/captures.

    That archive is the evidence base for two open questions — where
    _FOLLOWUP_MIN_RMS belongs, and whether the '[unk] [unk] [unk] onyx' false
    wakes are marginal or solid. Both are DISTRIBUTION questions, so
    test-generated records are not merely noise: they are the same fixture
    clip and the same handful of RMS values, repeated once per suite run. A
    threshold calibrated from that would be measuring the fixtures.

    Rebinding the module attribute rather than the setting, because `enabled()`
    reads config and several tests legitimately turn archiving ON to assert
    that it writes.
    """
    from backend.core import capture_archive

    tmp = tmp_path_factory.mktemp("captures")
    real = capture_archive._ARCHIVE_DIR
    capture_archive._ARCHIVE_DIR = tmp
    try:
        yield tmp
    finally:
        capture_archive._ARCHIVE_DIR = real


@pytest.fixture(autouse=True, scope="session")
def _isolate_contact_book(tmp_path_factory):
    """Keep the suite out of the user's real contacts file.

    Same hazard as the ledger above, with a sharper edge: backend/database/
    contacts.json holds real people's phone numbers. A test calling the
    add_contact or delete_contact TOOL reaches the module-level singleton, not
    a fixture — so without this, one such test would write into (or delete
    from) the user's actual contacts. The store tests build their own
    ContactBook and are unaffected either way; this exists for everything that
    goes through the tool layer.
    """
    from backend.core import contacts

    tmp = tmp_path_factory.mktemp("contacts") / "contacts.json"
    real = contacts.book
    contacts.book = contacts.ContactBook(tmp)
    try:
        yield contacts.book
    finally:
        contacts.book = real


@pytest.fixture(autouse=True)
def _no_real_desktop(monkeypatch):
    """No test may read the real foreground window: its title is whatever the
    user has open (a browser tab, a document name) — private, and different
    on every run. type_text's confirmation reads it; tests get a neutral fake.
    Tests that need a particular window patch files.foreground_window again."""
    from backend.core.tools import files
    monkeypatch.setattr(files, "foreground_window",
                        lambda: {"hwnd": 1, "pid": 1, "title": "test window", "process": "test.exe",
                                 "class": "TestWindow"})
