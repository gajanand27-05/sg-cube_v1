"""A confirmation for an outbound message must say what will be sent.

The prompt used to name only the tool:

    I need your permission to send whatsapp. Should I proceed?

Which is unanswerable in the way that matters. It cannot catch the two things
that actually go wrong on this path:

  * a false wake — '[unk] [unk] [unk] onyx' fired a real turn in a live log —
    putting words into a message the user never dictated;
  * a misheard message. STT dropped a whole word from "I need to send a
    whatsapp message to Sharath", and dropped the 'd' from the user's own name
    twice in one utterance.

"Yes" to "permission to send whatsapp" authorises an unknown message to an
unknown person. This is also the safety net PendingClarification leans on, so
it has to be able to carry that weight before the clarification slot exists.

The yes/no classifier is deliberately untouched — only the question changes.
"""
import sys
from pathlib import Path

_root = Path(__file__).resolve().parents[1]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from backend.core.agents import commander as cmd


def _call(name, args):
    return {"name": name, "args": args}


def test_whatsapp_confirmation_names_the_recipient_and_the_message():
    """The regression, in the exact shape of the live turn."""
    readback = cmd._readback_args(
        _call("send_whatsapp",
              {"contact": "Sharath", "message": "Hi, how are you doing?"}))

    assert "Sharath" in readback, f"recipient missing from {readback!r}"
    assert "Hi, how are you doing?" in readback, (
        f"message body missing from {readback!r} — 'yes' would authorise a "
        "message the user never heard read back"
    )


def test_email_reads_back_recipient_and_subject():
    readback = cmd._readback_args(
        _call("send_email", {"to": "a@b.com", "subject": "Invoice",
                             "body": "please find attached"}))
    assert "a@b.com" in readback and "Invoice" in readback, readback


def test_send_to_phone_reads_back_the_content():
    readback = cmd._readback_args(_call("send_to_phone", {"content": "hello"}))
    assert "hello" in readback, readback


def test_a_non_messaging_tool_reads_back_nothing():
    """Scope. This is about outbound content the user cannot un-send, not a
    general argument dump — reading back every arg of every confirmation would
    make the prompt long enough to stop being read."""
    assert cmd._readback_args(_call("close_app", {"name": "chrome"})) == ""


def test_a_long_body_is_truncated():
    """It is spoken aloud. An unbounded read-back turns a confirmation into a
    recital the user talks over."""
    readback = cmd._readback_args(
        _call("send_email", {"to": "a@b.com", "subject": "x", "body": "word " * 200}))
    assert len(readback) < 300, f"read-back is {len(readback)} chars"


def test_a_missing_argument_does_not_crash_the_prompt():
    """The clarification path exists precisely because args arrive missing."""
    assert "Sharath" in cmd._readback_args(_call("send_whatsapp", {"contact": "Sharath"}))
    assert cmd._readback_args(_call("send_whatsapp", {})) == ""


def test_the_prompt_builder_uses_the_readback():
    """Wiring guard: a read-back computed and never spoken changes nothing."""
    import inspect

    src = inspect.getsource(type(cmd.commander)._run_loop_stream)
    assert "_readback_args" in src, (
        "the confirmation prompt is still built without the read-back"
    )


def test_every_outbound_comms_tool_has_a_readback():
    """Keeps the map from rotting.

    A new tool in comms.py tiered DESTRUCTIVE is by definition something the
    user cannot un-send. If one is added without a read-back entry, this fails
    rather than silently shipping an unanswerable confirmation.
    """
    import backend.core.tools as _tools  # noqa: F401  (registers them)
    from backend.core.tools.registry import REGISTRY, CapabilityTier

    missing = []
    for name, tool in REGISTRY.items():
        fn = getattr(tool, "fn", None) or getattr(tool, "func", None)
        module = getattr(fn, "__module__", "")
        if not module.endswith("tools.comms"):
            continue
        if tool.tier != CapabilityTier.DESTRUCTIVE:
            continue
        if name not in cmd._READBACK_FIELDS:
            missing.append(name)

    assert not missing, (
        f"outbound comms tools with no confirmation read-back: {missing}. "
        "Their confirmation would name the tool and nothing else, which "
        "cannot catch a false wake or a misheard message."
    )


if __name__ == "__main__":
    for _name, _fn in sorted(globals().items()):
        if _name.startswith("test_") and callable(_fn):
            print(f"  [SKIP] {_name} (needs pytest)")
