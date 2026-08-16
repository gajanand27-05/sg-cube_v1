"""What the assistant SPEAKS after "read my screen" has to be words.

Live dogfooding output:

    "Screen text: ¥ @o @xs OH Oa Ot so QP fir The kein to |Me QQ» ax @o <-t!\\ str!"

A full-screen OCR pass reads every toolbar icon as text. The spoken line was
the first 200 characters of that pass, and the top of a screen is browser
chrome — so the user reliably heard icon glyphs while the document text sat
further down, never reached.

Measured on a real 1920x1080 screen: confidence filtering does NOT fix this.
Junk was 24% of tokens at conf>=0 and still 18% at conf>=80 — Tesseract is
confident about its garbage. Word shape is the signal that separates them.

The filter applies to the PREVIEW only. The full pass stays in data["text"],
because the agent legitimately needs what this drops — error codes,
temperatures, prices, timestamps.
"""
import sys
from pathlib import Path

_project_root = Path(__file__).resolve().parents[1]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from backend.core.tools.ocr import _readable_preview, _word_shaped


def test_icon_glyphs_are_not_words():
    """Straight from the reported output."""
    for junk in ["¥", "@o", "|Me", "QQ»", "<-t!\\", "€", "»", "@1", "~", "@tc"]:
        assert not _word_shaped(junk), repr(junk)


def test_real_words_survive():
    for word in ["Partly", "cloudy", "PowerShell", "Episodic", "summarization",
                 "inbox", "Gemini", "failed:", "onyx"]:
        assert _word_shaped(word), repr(word)


def test_the_filter_is_lossy_and_that_is_why_it_is_preview_only():
    """Documents the cost honestly: these are dropped from the SPOKEN line.
    They must still reach the agent through data["text"], which is why the
    filter is not applied to the full pass — see test below."""
    for dropped in ["27°C", "0x80070005", "5624", "$19.99", "12:45"]:
        assert not _word_shaped(dropped), repr(dropped)


class _FakePyt:
    """Stands in for pytesseract with a known image_to_data payload.

    Rows are (text, conf) or (text, conf, line). Line defaults to 0 so the
    token-level tests read as one line.
    """
    def __init__(self, rows, raises=False):
        self._rows, self._raises = rows, raises

    def image_to_data(self, image, output_type=None):
        if self._raises:
            raise RuntimeError("tesseract exploded")
        n = len(self._rows)
        return {
            "text": [r[0] for r in self._rows],
            "conf": [r[1] for r in self._rows],
            "block_num": [0] * n,
            "par_num": [0] * n,
            "line_num": [(r[2] if len(r) > 2 else 0) for r in self._rows],
        }


def _preview(rows, **kw):
    import backend.core.tools.ocr as ocr_mod
    fake = _FakePyt(rows)
    # _readable_preview imports Output from pytesseract; the real package is
    # installed, so only the data call needs faking.
    return ocr_mod._readable_preview(fake, object(), **kw)


def test_preview_keeps_only_words():
    rows = [("¥", 91), ("@o", 88), ("Partly", 95), ("cloudy", 96),
            ("|Me", 80), ("Windows", 93), ("PowerShell", 92)]
    assert _preview(rows) == "Partly cloudy Windows PowerShell"


def test_preview_drops_low_confidence_tokens():
    rows = [("Partly", 95), ("cloudy", 10), ("Windows", 93)]
    assert _preview(rows) == "Partly Windows"


def test_preview_handles_tesseracts_minus_one_confidence():
    """image_to_data emits conf "-1" for layout rows with no text, and emits
    conf as a STRING. Phrase-length fixture on purpose — a single surviving
    token would be dropped by the line rule and this test would then be
    measuring that instead of the conf parsing it is named for."""
    rows = [("", "-1", 1), ("Partly", "95", 1), ("  ", "-1", 1), ("cloudy", "96", 1)]
    assert _preview(rows) == "Partly cloudy"


def test_preview_respects_the_limit():
    rows = [("word", 90)] * 200
    assert len(_preview(rows, limit=50)) <= 50


def test_preview_never_raises_and_degrades_to_empty():
    """A failure here must not turn a successful read into an error — the
    caller falls back to the raw head."""
    import backend.core.tools.ocr as ocr_mod
    assert ocr_mod._readable_preview(_FakePyt([], raises=True), object()) == ""


def test_icon_rows_that_survive_token_filtering_are_dropped_by_line():
    """The residue after token filtering, measured on a real screen:
    "Qo sc ire he Mie Op ax Br ado ao" — all letters, so no charset or ratio
    test can touch them. What gives them away is the shape of the LINE: a
    couple of very short tokens rather than a phrase."""
    rows = [
        ("Qo", 90, 1), ("sc", 90, 1),          # icon row, 4 letters
        ("ire", 90, 2), ("he", 90, 2),          # icon row, 5 letters
        ("Episodic", 95, 3), ("summarization", 95, 3), ("failed", 95, 3),
    ]
    assert _preview(rows) == "Episodic summarization failed"


def test_a_short_but_real_label_is_kept():
    """The threshold is mild on purpose. "Ask Gemini" is two tokens and may be
    exactly what the user asked about — over-filtering would answer a question
    about the screen by hiding the screen."""
    assert _preview([("Ask", 95, 1), ("Gemini", 95, 1)]) == "Ask Gemini"


def test_a_lone_word_on_its_own_line_is_dropped():
    """One token is not a phrase; on a desktop it is almost always an icon
    caption."""
    rows = [("Downloads", 95, 1),
            ("Episodic", 95, 2), ("summarization", 95, 2), ("failed", 95, 2)]
    assert _preview(rows) == "Episodic summarization failed"


def test_line_order_is_preserved():
    rows = [("hello", 95, 1), ("there", 95, 1), ("second", 95, 2), ("line", 95, 2)]
    assert _preview(rows) == "hello there second line"


def test_full_text_is_not_filtered():
    """Wiring guard. The tool must return the unfiltered pass in data["text"];
    if the filter ever leaks onto the full text, the agent silently loses every
    number on screen and "read the error code" stops working."""
    import inspect
    from backend.core.tools import ocr as ocr_mod
    src = inspect.getsource(ocr_mod.ocr_screen)
    assert 'data={"text": truncated' in src, (
        "data['text'] should carry the raw truncated pass, not the preview"
    )
    assert "spoken_preview or truncated" in src


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  [PASS] {name}")
