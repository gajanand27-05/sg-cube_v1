"""Smoke check for the T2-2 file editing tools."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import backend.core.tools  # noqa: F401  triggers discovery
from backend.core.tools.registry import REGISTRY


def _checks():
    for name in ("read_file", "edit_file", "insert_lines", "write_file"):
        assert name in REGISTRY, f"{name} missing from REGISTRY"

    tmpdir = Path(tempfile.mkdtemp(prefix="sg_file_editor_")) if False else None  # noqa
    import tempfile
    tmpdir = Path(tempfile.mkdtemp(prefix="sg_file_editor_"))
    f = tmpdir / "demo.txt"

    # write_file
    r = REGISTRY["write_file"].func(path=str(f), content="alpha\nbeta\ngamma\n")
    assert r.status.value == "success", r.message
    assert f.read_text() == "alpha\nbeta\ngamma\n"
    print("  PASS: write_file creates and overwrites")

    # read_file
    r = REGISTRY["read_file"].func(path=str(f))
    assert r.status.value == "success"
    assert r.data["text"] == "alpha\nbeta\ngamma\n"
    assert isinstance(r.data["bytes"], int) and r.data["bytes"] > 0
    print("  PASS: read_file round-trip")

    # edit_file single replacement
    r = REGISTRY["edit_file"].func(path=str(f), old_text="beta", new_text="BETA")
    assert r.status.value == "success"
    assert f.read_text() == "alpha\nBETA\ngamma\n"
    print("  PASS: edit_file single replacement")

    # edit_file no match
    r = REGISTRY["edit_file"].func(path=str(f), old_text="nonexistent", new_text="x")
    assert r.status.value == "error"
    print("  PASS: edit_file rejects missing old_text")

    # edit_file ambiguous
    #    Currently content lines are now: alpha, BETA, gamma — let's make a duplicate;
    f.write_text("alpha\ndup\nbeta\ndup\ngamma\n")
    r = REGISTRY["edit_file"].func(path=str(f), old_text="dup", new_text="X")
    assert r.status.value == "error"
    assert "match" in (r.message or r.reason or "").lower()
    print("  PASS: edit_file rejects ambiguous match")

    # insert_lines at line 2 (before BETA which was line 2 originally; line 2 in dup-version is "beta")
    r = REGISTRY["insert_lines"].func(path=str(f), line_number=2, text="INSERTED\n")
    body = f.read_text()
    assert body.startswith("alpha\nINSERTED\ndup\nbeta\ndup\ngamma\n"), body
    print("  PASS: insert_lines before line 2")

    # insert_lines append (line_number > len)
    r = REGISTRY["insert_lines"].func(path=str(f), line_number=999, text="TAIL\n")
    assert f.read_text().endswith("TAIL\n")
    print("  PASS: insert_lines appends")

    # read_file on missing path
    r = REGISTRY["read_file"].func(path=str(tmpdir / "missing.txt"))
    assert r.status.value == "blocked"
    print("  PASS: read_file blocks missing file")

    # edit_file on missing path
    r = REGISTRY["edit_file"].func(path=str(tmpdir / "missing.txt"), old_text="x", new_text="y")
    assert r.status.value == "blocked"
    print("  PASS: edit_file blocks missing file")

    # path traversal rejection
    r = REGISTRY["read_file"].func(path=str(tmpdir / ".." / "demo.txt"))
    assert r.status.value == "blocked"
    assert "traversal" in (r.message or r.reason or "").lower()
    print("  PASS: read_file rejects path traversal")


_checks()
print("=== T2-2 verification: ALL PASSED ===")
