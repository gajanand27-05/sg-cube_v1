"""Short-term conversation memory for the agent.

Holds the last N user/assistant exchanges so the LLM can resolve follow-ups
("louder", "more like that", "and then close it"). Single global instance —
the daemon is single-user. Add per-user keying when multi-user lands.
"""
from collections import deque
from dataclasses import dataclass


@dataclass
class Turn:
    role: str  # "user" | "assistant"
    text: str


class ConversationContext:
    def __init__(self, max_turns: int = 10) -> None:
        # max_turns counts individual messages (5 user + 5 assistant = 10)
        self.turns: deque[Turn] = deque(maxlen=max_turns)

    def add_user(self, text: str) -> None:
        self.turns.append(Turn("user", text))

    def add_assistant(self, text: str) -> None:
        self.turns.append(Turn("assistant", text))

    def render(self) -> list[dict]:
        """Return the history in OpenAI/Ollama chat format."""
        return [{"role": t.role, "content": t.text} for t in self.turns]

    def clear(self) -> None:
        self.turns.clear()


_global_context: ConversationContext | None = None


def get_context() -> ConversationContext:
    """Process-wide singleton. Cleared on daemon restart."""
    global _global_context
    if _global_context is None:
        _global_context = ConversationContext()
    return _global_context
