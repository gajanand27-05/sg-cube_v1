import logging
from enum import Enum
from typing import Optional

from backend.core.events import bus

log = logging.getLogger(__name__)


class AssistantState(str, Enum):
    IDLE = "IDLE"
    LISTENING = "LISTENING"
    THINKING = "THINKING"
    EXECUTING = "EXECUTING"
    SPEAKING = "SPEAKING"
    ERROR = "ERROR"


class StateChangedEvent:
    def __init__(self, old_state: AssistantState, new_state: AssistantState):
        self.old_state = old_state
        self.new_state = new_state

    def __repr__(self):
        return f"<StateChanged: {self.old_state} -> {self.new_state}>"


class StateMachine:
    """Manages the assistant's current state and publishes transitions."""

    def __init__(self):
        self._current_state = AssistantState.IDLE

    @property
    def current(self) -> AssistantState:
        return self._current_state

    def transition_to(self, new_state: AssistantState):
        if self._current_state == new_state:
            return

        old_state = self._current_state
        self._current_state = new_state
        log.info(f"State: {old_state} -> {new_state}")
        
        # Publish the change to the bus so the UI and other modules can react
        bus.publish(StateChangedEvent(old_state, new_state))


# Global instance
manager = StateMachine()
