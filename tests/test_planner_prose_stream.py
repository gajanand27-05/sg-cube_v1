"""The assistant must not speak the Planner's JSON envelope — T-tts-speaks-planner-json.

brain.py accumulated raw Planner tokens into sentence_buffer and fired tts_ready
whenever _is_sentence_complete() saw punctuation. The Planner emits JSON, so the
punctuation it tripped on was JSON punctuation and Piper spoke
`{"final_response":"Got it!` aloud on every streaming voice turn.

These prove the extractor and the brain wiring. They do NOT prove the pipeline —
asserting "no { in tts_ready" passes happily while the speaker stays broken. See
the live-turn probe in the session report for what actually reached Piper.
"""
import sys
from pathlib import Path

import pytest

_project_root = Path(__file__).resolve().parents[1]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from backend.core.agents.prose_stream import FinalResponseExtractor


def feed_all(tokens) -> str:
    """Stream tokens through a fresh extractor, return the assembled prose."""
    ex = FinalResponseExtractor()
    return "".join(ex.feed(t) for t in tokens)


def char_tokens(text: str):
    """Worst-case tokenization: one character at a time."""
    return list(text)


ENVELOPE = '{"final_response": "Got it! Jupiter is the largest planet."}'
EXPECTED = "Got it! Jupiter is the largest planet."


# ── The value comes out, the envelope does not ─────────────────────────

def test_extracts_the_value_from_a_whole_envelope():
    assert feed_all([ENVELOPE]) == EXPECTED


def test_extracts_the_value_one_character_at_a_time():
    """Token boundaries respect nothing — the state machine must survive the
    key, the colon and the opening quote arriving in separate deltas."""
    assert feed_all(char_tokens(ENVELOPE)) == EXPECTED


def test_realistic_llm_tokenization():
    tokens = ['{"', "final", "_response", '":', ' "', "Got", " it", "!",
              " Jupiter", " is", " the", " largest", " planet", '."', "}"]
    assert feed_all(tokens) == EXPECTED


def test_no_envelope_characters_ever_escape():
    out = feed_all(char_tokens(ENVELOPE))
    for forbidden in ('{', '}', '"final_response"', ':'):
        assert forbidden not in out, f"{forbidden!r} leaked into speech"


def test_markdown_fenced_envelope():
    """The Planner sometimes wraps its JSON in a ```json fence."""
    fenced = '```json\n{"final_response": "All done."}\n```'
    assert feed_all(char_tokens(fenced)) == "All done."


def test_prose_before_the_envelope_is_skipped():
    """A model that prefixes chat before the JSON must not have that spoken."""
    messy = 'Sure, here you go:\n{"final_response": "The answer is four."}'
    assert feed_all(char_tokens(messy)) == "The answer is four."


def test_whitespace_around_the_colon():
    assert feed_all(char_tokens('{"final_response"   :   "Hi there."}')) == "Hi there."


# ── Tool-call turns produce no speech here ─────────────────────────────

def test_tool_calls_envelope_yields_nothing():
    """Correct: those turns speak after execution, not from the plan."""
    envelope = ('{"tool_calls": [{"name": "open_app", "args": {"target": "chrome"}, '
                '"confidence": 0.9, "reasoning": "user asked to open chrome"}]}')
    assert feed_all(char_tokens(envelope)) == ""


def test_long_tool_envelope_does_not_grow_the_scan_buffer():
    ex = FinalResponseExtractor()
    for _ in range(500):
        ex.feed('{"tool_calls":[{"name":"x","args":{"a":"bbbbbbbbbbbbbbbb"}}]}')
    assert len(ex._scan) <= 256 + len('{"tool_calls":[{"name":"x","args":{"a":"bbbbbbbbbbbbbbbb"}}]}')
    assert ex.started is False


# ── JSON escapes ───────────────────────────────────────────────────────

def test_escaped_quote_is_unescaped_and_does_not_terminate():
    envelope = r'{"final_response": "She said \"hello\" to me."}'
    assert feed_all(char_tokens(envelope)) == 'She said "hello" to me.'


def test_escaped_newline_and_backslash():
    envelope = r'{"final_response": "Line one.\nLine two.\\done"}'
    assert feed_all(char_tokens(envelope)) == "Line one.\nLine two.\\done"


def test_unicode_escape_split_across_tokens():
    """\\u2192 is exactly the character that crashed the logger — it has to
    survive arriving four tokens late."""
    tokens = ['{"final_response": "step one \\', "u", "21", "92", ' step two."}']
    assert feed_all(tokens) == "step one → step two."


def test_surrogate_escapes_are_dropped_not_emitted():
    """An emoji arrives as a \\ud83d\\ude00 surrogate pair. Emitting either half
    raises on the next UTF-8 encode and would take a log handler down — the same
    failure class as T-log-cp1252."""
    # The JSON text is literally: hi 😀 there
    envelope = '{"final_response": "hi \\ud83d\\ude00 there"}'
    out = feed_all(char_tokens(envelope))
    assert out == "hi  there"
    out.encode("utf-8")  # must not raise


def test_literal_non_ascii_passes_through():
    """Not every non-ASCII character is escaped; a raw one must survive."""
    out = feed_all(char_tokens('{"final_response": "café — done."}'))
    assert out == "café — done."
    out.encode("utf-8")


def test_malformed_unicode_escape_is_literal_not_fatal():
    out = feed_all(char_tokens(r'{"final_response": "code \uZZZZ end"}'))
    assert "end" in out


# ── Termination ────────────────────────────────────────────────────────

def test_stops_at_the_closing_quote():
    ex = FinalResponseExtractor()
    out = ex.feed('{"final_response": "Done."}, "extra": "not spoken"')
    assert out == "Done."
    assert ex.done is True
    assert ex.feed(' more text') == "", "nothing may follow the closing quote"


def test_incomplete_stream_yields_what_arrived():
    """A truncated generation should still have spoken what it managed."""
    ex = FinalResponseExtractor()
    out = ex.feed('{"final_response": "The first part is here')
    assert out == "The first part is here"
    assert ex.done is False


def test_empty_and_none_deltas():
    ex = FinalResponseExtractor()
    assert ex.feed("") == ""
    assert ex.feed('{"final_response": "ok."}') == "ok."


# ── The brain wiring ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_brain_speaks_prose_and_never_the_envelope():
    """Drive Brain.run_stream with a Commander that streams a real envelope and
    assert every tts_ready chunk is prose."""
    from backend.core.brain import Brain, BrainRequest
    from backend.core.agents.commander import CommanderChunk
    from backend.core.agents.prose_stream import FinalResponseExtractor as FRE

    envelope = ('{"final_response": "Got it. Jupiter is the largest planet in '
                'the solar system. It is a gas giant."}')

    class _FakeCommander:
        async def run_stream(self, text, conversation, user_id):
            ex = FRE()
            for ch in envelope:                      # one char per token
                yield CommanderChunk("token", ch)
                speakable = ex.feed(ch)
                if speakable:
                    yield CommanderChunk("prose", speakable)
            yield CommanderChunk("final_response",
                                 "Got it. Jupiter is the largest planet in "
                                 "the solar system. It is a gas giant.")

    brain = Brain()
    brain.commander = _FakeCommander()

    spoken, tokens = [], []
    async for chunk in brain.run_stream(BrainRequest(input_text="tell me about jupiter",
                                                     user_id="u", session_id="s",
                                                     input_mode="text")):
        if chunk.type == "tts_ready":
            spoken.append(chunk.content)
        elif chunk.type == "token":
            tokens.append(chunk.content)

    assert spoken, "nothing was queued for speech"
    for sentence in spoken:
        assert "{" not in sentence and "}" not in sentence
        assert "final_response" not in sentence
    assert " ".join(spoken).startswith("Got it.")
    # Raw tokens still flow: the UI ticker and planner_first_token need them.
    assert "".join(tokens) == envelope


@pytest.mark.asyncio
async def test_tool_call_turn_queues_no_speech_from_the_plan():
    from backend.core.brain import Brain, BrainRequest
    from backend.core.agents.commander import CommanderChunk

    envelope = '{"tool_calls": [{"name": "open_app", "args": {"target": "chrome"}}]}'

    class _FakeCommander:
        async def run_stream(self, text, conversation, user_id):
            for ch in envelope:
                yield CommanderChunk("token", ch)
            yield CommanderChunk("final_response", "Opening Chrome.")

    brain = Brain()
    brain.commander = _FakeCommander()

    spoken = []
    async for chunk in brain.run_stream(BrainRequest(input_text="open chrome",
                                                     user_id="u", session_id="s",
                                                     input_mode="text")):
        if chunk.type == "tts_ready":
            spoken.append(chunk.content)

    assert spoken == [], f"a tool plan was queued for speech: {spoken}"
