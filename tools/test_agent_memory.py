import asyncio
import sys
import time
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.core.agent import agent
from backend.core.agent.context import ConversationContext

async def test_agent_with_memory():
    print("── TESTING AGENT + SEMANTIC MEMORY ────────────────")
    ctx = ConversationContext()
    
    query = "What is my favorite car color?"
    print(f"\nUser: {query}")
    
    t0 = time.perf_counter()
    spoken, records = await agent.run(query, ctx)
    elapsed_ms = (time.perf_counter() - t0) * 1000
    
    print(f"\nSG_CUBE: {spoken}")
    print(f"Latency: {elapsed_ms:.0f}ms")
    
    if "midnight blue" in spoken.lower():
        print("\n✅ SUCCESS: Agent successfully retrieved and used semantic memory!")
    else:
        print("\n❌ FAILURE: Agent did not mention the car color from memory.")

if __name__ == "__main__":
    asyncio.run(test_agent_with_memory())
