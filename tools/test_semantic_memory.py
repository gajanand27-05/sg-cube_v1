import asyncio
import sys
from pathlib import Path
from datetime import datetime

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.core.memory.manager import memory as memory_manager
from backend.core.memory.episodic import summarizer as episodic_summarizer

async def run_tests():
    print("── PHASE 12: SEMANTIC MEMORY TESTS ────────────────")
    
    # Test 1: Explicit Store
    print("\n[Test 1] Storing: 'My favorite car color is midnight blue.'")
    memory_manager.remember_fact("My favorite car color is midnight blue.", metadata={"test": "true"})
    print("Done.")

    # Test 2: Semantic Recall
    # We query for 'vehicle' but the fact is about 'car'
    query = "What color vehicle would I probably buy?"
    print(f"\n[Test 2] Recalling for: '{query}'")
    context = memory_manager.get_relevant_context(query)
    print("Context retrieved:")
    print(context)
    
    if "midnight blue" in context:
        print("\n✅ SUCCESS: Semantic recall worked (car <-> vehicle).")
    else:
        print("\n❌ FAILURE: Semantic recall did not find the car fact.")

    # Test 3: Store Important Preference
    fact3 = "I prefer dark amber terminal themes."
    print(f"\n[Test 3] Storing (Important): '{fact3}'")
    memory_manager.remember_preference(fact3, metadata={"importance": 1.0})
    
    # Let's verify Test 3 with a semantic query too
    query3 = "What should my terminal look like?"
    print(f"Verifying Test 3 with query: '{query3}'")
    context3 = memory_manager.get_relevant_context(query3)
    print("Context retrieved:")
    print(context3)
    
    if "dark amber" in context3:
        print("\n✅ SUCCESS: Theme preference recalled semantically.")
    else:
        print("\n❌ FAILURE: Theme preference not found.")

if __name__ == "__main__":
    try:
        asyncio.run(run_tests())
    except Exception as e:
        print(f"\nFATAL ERROR during test: {e}")
        print("\nMake sure Ollama is running and 'nomic-embed-text' is pulled.")
        print("Command: ollama pull nomic-embed-text")
