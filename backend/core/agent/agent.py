from backend.core.agents.commander import commander
from backend.core.agent.context import ConversationContext


async def run(text: str, context: ConversationContext) -> tuple[str, list[dict]]:
    """Legacy interface for the new Multi-Agent Internal Architecture."""
    return await commander.run(text, context)
