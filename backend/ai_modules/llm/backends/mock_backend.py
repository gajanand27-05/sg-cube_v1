"""Mock backend — deterministic responses for testing."""
from typing import Any, AsyncGenerator
from collections import deque

from backend.ai_modules.llm.provider import LLMBackend


class MockBackend(LLMBackend):
    """Mock backend for tests — returns predefined responses."""

    def __init__(self):
        self.responses: deque[str] = deque()
        self.stream_responses: deque[list[str]] = deque()

    def add_response(self, text: str) -> None:
        self.responses.append(text)

    def add_stream_response(self, tokens: list[str]) -> None:
        self.stream_responses.append(tokens)

    async def generate(
        self,
        prompt: str,
        *,
        system: str = "",
        temperature: float = 0.0,
        json_mode: bool = False,
        **kwargs: Any,
    ) -> str:
        if self.responses:
            return self.responses.popleft()
        return '{"action": "respond", "target": "mock response", "args": {}}'

    async def chat_stream(
        self,
        messages: list[dict],
        *,
        temperature: float = 0.2,
        json_mode: bool = False,
        **kwargs: Any,
    ) -> AsyncGenerator[dict, None]:
        if self.stream_responses:
            tokens = self.stream_responses.popleft()
        else:
            tokens = ["mock", " ", "stream", " ", "response"]
        for token in tokens:
            yield {"token": token, "done": False}
        yield {"token": "", "done": True}

    def embed(self, text: str, **kwargs: Any) -> list[float]:
        return [0.1] * 768

    async def aembed(self, text: str, **kwargs: Any) -> list[float]:
        return [0.1] * 768