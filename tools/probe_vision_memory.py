import asyncio
import sys
from pathlib import Path
from datetime import datetime

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.core.memory.screen_memory import screen_memory
from backend.core.memory.manager import memory as memory_manager

async def test_vision_rag():
    print("── PHASE 13: SCREEN-MEMORY TESTS ────────────────")
    
    # 1. Simulate a Visual Observation
    # In a real run, this comes from VLM (qwen2.5-vl) after a screenshot
    observation = {
        "app": "VS Code",
        "summary": "User is writing a Python implementation of a Vector Database using ChromaDB.",
        "keywords": ["python", "chromadb", "backend"]
    }
    
    print("\n[Step 1] Storing simulated visual observation...")
    screen_memory.store_observation(observation)
    print("Done.")

    # 2. Test Semantic Retrieval
    # We query for something related to the observation
    query = "What code was I working on earlier?"
    print(f"\n[Step 2] Querying: '{query}'")
    context = memory_manager.get_relevant_context(query)
    
    print("\nContext injected into Agent:")
    print(context)
    
    if "VS Code" in context and "ChromaDB" in context:
        print("\n✅ SUCCESS: Agent recalled the visual context semantically.")
    else:
        print("\n❌ FAILURE: Visual context not found in RAG.")

if __name__ == "__main__":
    asyncio.run(test_vision_rag())
