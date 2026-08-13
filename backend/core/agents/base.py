import logging
from typing import Any, List, Optional

from backend.core.events import get_bus
# NOT local copies. This module used to define its own InternalAgentEvent and
# TokenStreamEvent shadowing the ones in daemon.ui_events, and the bus keys
# subscribers on the class OBJECT — so every _emit() below published a class
# that ws_ui.TYPE_MAP had never heard of and AgentRegistry had not subscribed
# to. Twelve _emit call sites across Guardian, Operator and Planner went
# nowhere: no "agent_status" ever crossed the wire, and /agents/status stayed
# empty. Identical shape to the duplicate SelfHealingEvent removed in 6720ca3.
from backend.daemon.ui_events import InternalAgentEvent, TokenStreamEvent

log = logging.getLogger(__name__)


class BaseInternalAgent:
    """Base class for specialized reasoning roles."""

    def __init__(self, name: str):
        self.name = name

    def _emit(self, action: str, **kwargs):
        """Notify the system via the event bus."""
        event = InternalAgentEvent(agent_name=self.name, action=action, details=kwargs)
        get_bus().publish(event)
        log.debug(f"Agent {self.name} -> {action}: {kwargs}")
