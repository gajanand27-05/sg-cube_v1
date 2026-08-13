"""Every Tesseract caller must resolve the binary the same way.

The UB-Mannheim Windows installer does not add tesseract.exe to PATH, so
`pytesseract`'s own lookup fails on a perfectly good install. vision/ocr_reader
grew tesseract_path() for that on 2026-08-13; tools/ocr.py did not, and kept
reporting "Tesseract binary not found on PATH" with the engine installed at the
default location. Phone-camera OCR worked, screen OCR did not, and the two
looked identical from the outside.

That is the third time in one session that a fix landed on one caller and not
its sibling (ws_ui/remote bridges, embed/generate connect timeouts, and this).
Hence a test that names every caller rather than the one that was broken.
"""
import ast
import sys
from pathlib import Path

import pytest

_root = Path(__file__).resolve().parents[1]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from backend.core.vision.ocr_reader import tesseract_path

BACKEND = _root / "backend"


def _modules_importing_pytesseract() -> list[Path]:
    out = []
    for path in BACKEND.rglob("*.py"):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import) and any(a.name == "pytesseract" for a in node.names):
                out.append(path)
                break
            if isinstance(node, ast.ImportFrom) and node.module == "pytesseract":
                out.append(path)
                break
    return out


def test_there_is_more_than_one_caller_to_keep_in_step():
    """If this drops to one, the drift this file guards cannot happen and the
    test below is checking nothing."""
    callers = _modules_importing_pytesseract()
    assert len(callers) >= 2, f"expected several pytesseract callers, found {callers}"


def test_every_pytesseract_caller_uses_the_shared_resolver():
    offenders = []
    for path in _modules_importing_pytesseract():
        src = path.read_text(encoding="utf-8")
        if "tesseract_path" not in src:
            offenders.append(path.relative_to(_root).as_posix())
    assert not offenders, (
        "these modules call pytesseract without resolving the binary through "
        "tesseract_path(), so they will report 'not found' on a working "
        "install: " + ", ".join(offenders)
    )


@pytest.mark.skipif(tesseract_path() is None, reason="Tesseract not installed")
def test_screen_ocr_actually_reads_the_screen():
    """The demo path: 'read my screen'. Was returning an error with Tesseract
    installed, which is indistinguishable from the feature not existing."""
    from backend.core.tools.ocr import ocr_screen

    fn = getattr(ocr_screen, "func", ocr_screen)
    result = fn()
    assert result.status.value in ("success", "blocked"), (
        f"screen OCR failed: {result.reason!r}"
    )
    if result.status.value == "success":
        assert result.data.get("chars", 0) > 0
