import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.core.memory.manager import memory as memory_manager

async def verify_context():
    query = "What is my favorite car color?"
    print(f"Query: {query}")
    context = memory_manager.get_relevant_context(query)
    print("--- CONTEXT ---")
    print(context)
    print("---------------")

if __name__ == "__main__":
    asyncio.run(verify_context())
