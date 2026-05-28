from collections import deque
from backend.core.agent.context import Turn

class ShortTermMemory:
    """Session-based chat history."""
    def __init__(self, max_turns: int = 15):
        self.turns: deque[Turn] = deque(maxlen=max_turns)

    def add(self, role: str, text: str):
        self.turns.append(Turn(role, text))

    def render(self) -> list[dict]:
        return [{"role": t.role, "content": t.text} for t in self.turns]

    def clear(self):
        self.turns.clear()
