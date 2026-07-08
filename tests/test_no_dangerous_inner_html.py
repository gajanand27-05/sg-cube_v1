"""Phase 3 structural safety test.

`dangerouslySetInnerHTML` in the canvas path would turn every field the
assistant emits into potential markup — a stored-XSS surface fed by
Phase 2's browser tools. React's default {value} text rendering is the
whole defence against that.

This test greps the frontend source. Not clever — but the exact
regression barrier: someone adds `dangerouslySetInnerHTML` anywhere in
the app, this test fails at CI time before it ever ships.
"""
import sys
from pathlib import Path

_project_root = Path(__file__).resolve().parents[1]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))


def test_no_dangerously_set_inner_html_anywhere_in_frontend_src():
    """No file under frontend/src/ may use dangerouslySetInnerHTML. If a
    legitimate need appears later (e.g. rendering trusted markdown),
    whitelist that specific file explicitly in this test — don't remove
    the check."""
    src = _project_root / "frontend" / "src"
    if not src.is_dir():
        import pytest
        pytest.skip(f"frontend/src not found at {src}")

    # Look for ACTUAL React usage (JSX prop or object key), not the token
    # appearing in a comment. React usage always looks like
    # `dangerouslySetInnerHTML=` (JSX prop) or `"dangerouslySetInnerHTML":`
    # (dict key). Neither pattern appears in prose comments.
    import re as _re
    usage = _re.compile(r'dangerouslySetInnerHTML\s*[=:]')

    offenders: list[str] = []
    for path in src.rglob("*"):
        if path.suffix not in (".ts", ".tsx", ".js", ".jsx"):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except Exception:
            continue
        if usage.search(text):
            offenders.append(str(path.relative_to(_project_root)))

    assert offenders == [], (
        f"dangerouslySetInnerHTML found in {offenders}. Load-bearing "
        f"XSS defence for the Phase 3 canvas — text fields must render via "
        f"React default escaping, not raw HTML injection. If you have a "
        f"legitimate trusted-markdown need, whitelist the specific file "
        f"in this test rather than removing the check."
    )
    print(f"  [PASS] no dangerouslySetInnerHTML in frontend/src (canvas defence intact)")


def test_canvas_widget_render_uses_default_text_rendering():
    """Assert CanvasWidgets.tsx renders text fields as JSX children,
    which React default-escapes. Belt-and-suspenders with the grep
    above."""
    widgets_path = _project_root / "frontend" / "src" / "components" / "CanvasWidgets.tsx"
    if not widgets_path.is_file():
        import pytest
        pytest.skip("CanvasWidgets.tsx not found")

    text = widgets_path.read_text(encoding="utf-8")
    for expected in ("{w.title}", "{w.body}", "{it.text}"):
        assert expected in text, (
            f"expected JSX escaped rendering of {expected} in CanvasWidgets.tsx — "
            f"if this was refactored, verify the new path still escapes text via React default"
        )
    print("  [PASS] CanvasWidgets renders text via JSX default-escaping ({...} form)")


if __name__ == "__main__":
    test_no_dangerously_set_inner_html_anywhere_in_frontend_src()
    test_canvas_widget_render_uses_default_text_rendering()
    print("All Phase 3 structural safety tests passed.")
