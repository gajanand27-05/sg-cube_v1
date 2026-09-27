"""The trimmed planner tool list (off by default) and the Groq chat backend.

Trimmed: each tool as name(required, optional?) plus the first sentence of
its description. The first sentence alone lost argument names (set_reminder
got seconds/text on gemma4:31b), so the signature rides along.

Groq: OpenAI-style SSE parsed into the provider's {"token", "done"} chunks,
the provider's own token counts kept, reasoning text never yielded, and an
HTTP error raised with Groq's status and message. No request leaves the
machine: httpx runs on a MockTransport.
"""
import types

import httpx
import pytest

from backend.ai_modules.llm.backends import groq_backend
from backend.core.agents import planner as planner_mod


@pytest.mark.parametrize("text,first", [
    ("Open a desktop application by name. ANY installed app works.", "Open a desktop application by name."),
    ("Use e.g. notepad here. Then more.", "Use e.g. notepad here."),
    ("No full stop at all", "No full stop at all"),
    ("Version 3.12 works. Done.", "Version 3.12 works."),
])
def test_first_sentence(text, first):
    assert planner_mod._first_sentence(text) == first


def _cap(name, desc, props, required):
    return types.SimpleNamespace(
        name=name, description=desc, tags=[], security=types.SimpleNamespace(value="safe"),
        schema={"parameters": {"properties": {p: {} for p in props}, "required": required}})


def test_trimmed_line_keeps_the_argument_names(monkeypatch):
    monkeypatch.setattr(planner_mod.settings, "planner_short_tool_descriptions", True)
    monkeypatch.setattr("backend.core.safe_executor.command_whitelist._get_chrome_profiles", lambda: {})
    cap = _cap("set_reminder", 'Schedule a spoken reminder. After `minutes` minutes, it says "<message>".',
               ["minutes", "message", "repeat"], ["minutes", "message"])
    prompt = planner_mod.PlannerAgent()._build_prompt(
        types.SimpleNamespace(capabilities=[cap], long_term_memory=[], recent_events=[]))
    assert "- set_reminder(minutes, message, repeat?) (safe): Schedule a spoken reminder." in prompt
    assert "After `minutes`" not in prompt


def test_full_descriptions_are_the_default(monkeypatch):
    assert planner_mod.settings.planner_short_tool_descriptions is False


# ── Groq backend ─────────────────────────────────────────────────────────

SSE = (
    'data: {"choices":[{"delta":{"reasoning":"thinking hard"}}]}\n\n'
    'data: {"choices":[{"delta":{"content":"{\\"final_"}}]}\n\n'
    'data: {"choices":[{"delta":{"content":"response\\": \\"hi\\"}"}}]}\n\n'
    'data: {"choices":[],"usage":{"prompt_tokens":3542,"completion_tokens":12,"completion_time":0.01}}\n\n'
    "data: [DONE]\n\n"
)


@pytest.fixture
def groq(monkeypatch):
    seen = {}

    def handler(request):
        seen["body"] = request.content
        seen["auth"] = request.headers.get("authorization")
        return seen.get("response") or httpx.Response(200, text=SSE)

    real = httpx.AsyncClient
    monkeypatch.setattr(groq_backend.httpx, "AsyncClient",
                        lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    monkeypatch.setattr(groq_backend.settings, "groq_api_key", "gsk_test")
    return seen


async def _collect(backend):
    return [c async for c in backend.chat_stream([{"role": "user", "content": "hi"}],
                                                 model="qwen/qwen3.8-27b")]


@pytest.mark.asyncio
async def test_stream_yields_content_only_and_keeps_usage(groq):
    b = groq_backend.GroqBackend()
    chunks = await _collect(b)
    assert "".join(c["token"] for c in chunks) == '{"final_response": "hi"}'
    assert chunks[-1] == {"token": "", "done": True}
    assert b.last_usage["prompt_tokens"] == 3542
    assert groq["auth"] == "Bearer gsk_test"
    assert b'"stream": true' in groq["body"] or b'"stream":true' in groq["body"]


@pytest.mark.asyncio
async def test_a_rate_limit_is_raised_with_groqs_message(groq):
    groq["response"] = httpx.Response(429, text='{"error":{"message":"Rate limit reached: tokens per minute"}}')
    with pytest.raises(httpx.HTTPStatusError, match="Groq 429.*tokens per minute"):
        await _collect(groq_backend.GroqBackend())
