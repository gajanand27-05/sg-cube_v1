"""dogfooding.json and gate_rejections.json: unreadable is not empty.

Both treated a file that failed to load as empty and then wrote the fresh
state over it (the ledger tried to rename it to .bak first, which fails on
Windows once a .bak exists). Now they leave an unreadable file untouched,
and every write is temp + fsync + replace with one .bak kept.
"""
import json

import pytest

from backend.core import capture_archive, json_file
from backend.core.dogfooding import Ledger


def test_json_file_distinguishes_missing_from_unreadable(tmp_path):
    assert json_file.read(tmp_path / "none.json") is None
    bad = tmp_path / "bad.json"
    bad.write_text("{half", encoding="utf-8")
    with pytest.raises(json_file.Unreadable):
        json_file.read(bad)


def test_json_file_write_keeps_one_backup(tmp_path):
    path = tmp_path / "s.json"
    json_file.write(path, {"v": 1})
    json_file.write(path, {"v": 2})
    json_file.write(path, {"v": 3})
    assert json.loads(path.read_text()) == {"v": 3}
    assert json.loads(path.with_suffix(".json.bak").read_text()) == {"v": 2}
    assert not path.with_suffix(".json.tmp").exists()


def test_an_unreadable_ledger_is_never_written_over(tmp_path):
    path = tmp_path / "dogfooding.json"
    path.write_text('{"wake_attempts": 41, "truncat', encoding="utf-8")
    path.with_suffix(".json.bak").write_text("{}", encoding="utf-8")  # the case the rename broke on
    ledger = Ledger(path)
    ledger.record_wake(True)
    ledger.record_command(True, 100)
    assert path.read_text(encoding="utf-8") == '{"wake_attempts": 41, "truncat'


def test_a_readable_ledger_still_saves(tmp_path):
    path = tmp_path / "dogfooding.json"
    ledger = Ledger(path)
    ledger.record_wake(True)
    assert json.loads(path.read_text())["wake_attempts"] == 1


def test_an_unreadable_gate_histogram_is_not_reset(tmp_path, monkeypatch):
    monkeypatch.setattr(capture_archive, "_ARCHIVE_DIR", tmp_path)
    monkeypatch.setattr(capture_archive, "enabled", lambda: True)
    path = tmp_path / capture_archive.GATE_REJECTIONS_FILE
    path.write_text('{"bins": {"100": 57}, "tot', encoding="utf-8")
    capture_archive.record_gate_rejection(120, floor=400)
    assert path.read_text(encoding="utf-8") == '{"bins": {"100": 57}, "tot'


def test_the_gate_histogram_still_counts(tmp_path, monkeypatch):
    monkeypatch.setattr(capture_archive, "_ARCHIVE_DIR", tmp_path)
    monkeypatch.setattr(capture_archive, "enabled", lambda: True)
    capture_archive.record_gate_rejection(120, floor=400)
    capture_archive.record_gate_rejection(130, floor=400)
    assert json.loads((tmp_path / capture_archive.GATE_REJECTIONS_FILE).read_text())["total"] == 2
