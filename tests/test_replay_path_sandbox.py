"""Audit HIGH-1: replay trace ids are path-sandboxed.

request_id flowed straight into REPLAY_DIR / f"{id}.json"; a "../" payload
reads any .json file on the machine. _trace_path rejects traversal in both
regex and resolved-path forms.
"""
import sys
from pathlib import Path

import pytest

_project_root = Path(__file__).resolve().parents[1]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from backend.server.routes.replay import REPLAY_DIR, _trace_path


def test_traversal_ids_rejected():
    for bad in ["../.env", "../../etc/passwd", "a/../../b", "..", ".env", "a/b", "/etc/passwd", ""]:
        with pytest.raises(Exception):
            _trace_path(bad)


def test_valid_ids_resolve_inside_replay_dir():
    for good in ["abc123", "turn-42", "2026-08-03_t1", "a.b_c", "x" * 128]:
        assert _trace_path(good) == (REPLAY_DIR / f"{good}.json").resolve()


def test_overlong_id_rejected():
    with pytest.raises(Exception):
        _trace_path("x" * 129)
