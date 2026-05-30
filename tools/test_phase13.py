import asyncio
import sys
import time
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.core.vision.capture import capture_screen
from backend.core.vision.vlm import analyze_screenshot
from backend.core.memory.screen_memory import screen_memory
from backend.core.agent import agent
from backend.core.agent.context import ConversationContext

async def manual_glance():
    print("── PHASE 13: MANUAL GLANCE ────────────────")
    
    # 1. Capture
    print("Capturing screen...")
    img_b64, title = capture_screen()
    if not img_b64:
        print("❌ Capture failed.")
        return
    print(f"Captured: {title}")

    # 2. Analyze (Local VLM)
    print("Analyzing with VLM (this may take a moment)...")
    observation = await analyze_screenshot(img_b64, title)
    if not observation:
        print("❌ VLM Analysis failed. Check if 'qwen2.5-vl' is pulled in Ollama.")
        return
    
    print("\nVLM Observation:")
    print(f"  App: {observation.get('app')}")
    print(f"  Summary: {observation.get('summary')}")
    print(f"  Keywords: {observation.get('keywords')}")

    # 3. Store
    print("\nStoring in semantic memory...")
    screen_memory.store_observation(observation)
    print("Done.")

async def ask_agent(query: str):
    print(f"\nUser: {query}")
    ctx = ConversationContext()
    spoken, records = await agent.run(query, ctx)
    print(f"SG_CUBE: {spoken}")

async def run_test_1():
    print("\n[TEST 1] 'What am I currently working on?'")
    await manual_glance()
    await ask_agent("What am I currently working on?")

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "glance":
        asyncio.run(manual_glance())
    else:
        asyncio.run(run_test_1())
