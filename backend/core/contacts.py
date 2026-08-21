"""Name -> phone number, and a refusal to guess which one.

"send hi to sharath" transcribed perfectly and still failed: send_whatsapp
takes a phone number with a country code, and nothing mapped a name to one.

The design risk is entirely in resolution. Speech recognition mangles names
("sherat" for "Sharat"), so exact-only matching would leave this as useless as
having no contacts at all — but messaging the WRONG person is irreversible,
and an assistant that quietly picks the nearest name will eventually send
something private to the wrong contact.

So: resolve only when exactly ONE candidate survives at the most precise tier
that matches anything. Ambiguity returns the candidate names instead of a
winner, so the caller can ask. Refusing costs one clarifying question; a
message sent to the wrong person cannot be recalled.

Storage mirrors the dogfooding ledger: a human-readable JSON file under
backend/database/, written via temp-file rename so a crash mid-write cannot
truncate it.
"""
from __future__ import annotations

import difflib
import json
import os
import re
import threading
from dataclasses import dataclass
from pathlib import Path

_DATA_DIR = Path(__file__).resolve().parents[1] / "database"
_CONTACTS_PATH = _DATA_DIR / "contacts.json"

# Matches send_whatsapp's own floor. Shorter than this is a typo or a
# shortcode, not something we should build a wa.me link from.
_MIN_DIGITS = 7

# difflib ratio below which two names are not the same name. Deliberately
# high: this is the tier that trades safety for usability, and every point
# lower widens the set of people a mis-heard name could reach.
_FUZZY_CUTOFF = 0.75

_ws = re.compile(r"\s+")


def _norm(name: str) -> str:
    return _ws.sub(" ", (name or "").strip().lower())


def digits_of(raw: str) -> str:
    return re.sub(r"[^\d]", "", raw or "")


def looks_like_a_number(raw: str) -> bool:
    return len(digits_of(raw)) >= _MIN_DIGITS


@dataclass(frozen=True)
class Contact:
    name: str
    number: str          # digits only, country code included


class ContactBook:
    def __init__(self, path: Path | None = None) -> None:
        self._path = Path(path) if path is not None else _CONTACTS_PATH
        self._lock = threading.RLock()
        self._contacts: list[Contact] = []
        self._load()

    # ── storage ──────────────────────────────────────────────────────────

    def _load(self) -> None:
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            rows = raw.get("contacts", []) if isinstance(raw, dict) else []
            self._contacts = [
                Contact(str(r["name"]), digits_of(str(r["number"])))
                for r in rows
                if isinstance(r, dict) and r.get("name") and r.get("number")
            ]
        except (OSError, ValueError, KeyError, TypeError):
            # A truncated or hand-edited file degrades to an empty book. It
            # must never be the reason a turn dies.
            self._contacts = []

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"contacts": [{"name": c.name, "number": c.number}
                                for c in self._contacts]}
        tmp = self._path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        os.replace(tmp, self._path)

    # ── mutation ─────────────────────────────────────────────────────────

    def add(self, name: str, number: str) -> Contact:
        """Add or update. Raises ValueError on a number we could not use —
        better here than as a dead wa.me link two layers away."""
        clean = _norm(name)
        if not clean:
            raise ValueError("contact needs a name")
        if not looks_like_a_number(number):
            raise ValueError(
                f"{number!r} is not a phone number with a country code")
        contact = Contact(_ws.sub(" ", name.strip()), digits_of(number))
        with self._lock:
            self._contacts = [c for c in self._contacts if _norm(c.name) != clean]
            self._contacts.append(contact)
            self._save()
        return contact

    def delete(self, name: str) -> bool:
        clean = _norm(name)
        with self._lock:
            before = len(self._contacts)
            self._contacts = [c for c in self._contacts if _norm(c.name) != clean]
            if len(self._contacts) == before:
                return False
            self._save()
            return True

    def all(self) -> list[Contact]:
        return list(self._contacts)

    # ── resolution ───────────────────────────────────────────────────────

    def _tiers(self, query: str) -> list[list[Contact]]:
        """Candidate sets, most precise first. Each tier is only consulted if
        every tier above it matched nothing."""
        q = _norm(query)
        if not q:
            return []
        exact = [c for c in self._contacts if _norm(c.name) == q]
        first = [c for c in self._contacts if _norm(c.name).split(" ")[0] == q]
        substr = [c for c in self._contacts if q in _norm(c.name)]

        names = {_norm(c.name): c for c in self._contacts}
        keys = list(names) + [n.split(" ")[0] for n in names]
        close = difflib.get_close_matches(q, keys, n=5, cutoff=_FUZZY_CUTOFF)
        fuzzy: list[Contact] = []
        for key in close:
            for c in self._contacts:
                n = _norm(c.name)
                if (n == key or n.split(" ")[0] == key) and c not in fuzzy:
                    fuzzy.append(c)
        return [t for t in (exact, first, substr, fuzzy) if t]

    def resolve(self, query: str) -> Contact | None:
        """The contact `query` unambiguously names, else None.

        A raw number short-circuits everything, so saying the digits works
        with an empty book.
        """
        if looks_like_a_number(query):
            return Contact(query.strip(), digits_of(query))
        tiers = self._tiers(query)
        if not tiers:
            return None
        best = tiers[0]
        return best[0] if len(best) == 1 else None

    def candidates(self, query: str) -> list[str]:
        """Names that `query` could have meant — what to read back when
        resolve() refused."""
        tiers = self._tiers(query)
        return sorted(c.name for c in tiers[0]) if tiers else []


book = ContactBook()
