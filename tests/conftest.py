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
import sys
from pathlib import Path

import pytest

_project_root = Path(__file__).resolve().parents[1]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))


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
