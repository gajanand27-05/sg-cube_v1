import asyncio
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.core.memory.timeline import timeline
from backend.core.memory.manager import memory

async def verify_timeline():
    print("── TIMELINE MEMORY VERIFICATION ────────────────")
    
    # 1. Record manual events
    print("Recording test events...")
    timeline.record_event("Opened SG_CUBE project", source="manual")
    
    # Simulate an event from 2 hours ago by manually injecting if needed,
    # but for now just record another one
    timeline.record_event("Viewed AIML notes", source="manual")
    timeline.record_event("Read HCAI paper", source="manual")
    
    # 2. Verify retrieval
    print("\nRetrieving recent timeline...")
    recent = timeline.get_recent_timeline(limit=5)
    for e in recent:
        print(f"- [{e.timestamp}] {e.content} (Source: {e.metadata.get('source')})")
    
    if len(recent) >= 3:
        print("\n✅ Events correctly recorded and retrieved.")
    else:
        print(f"\n❌ Expected 3+ events, got {len(recent)}.")

    # 3. Verify Agent Context Integration
    print("\nVerifying Agent Context...")
    context = memory.get_relevant_context("What was I doing?")
    print(context)
    
    if "Recent Activity Timeline:" in context and "Read HCAI paper" in context:
        print("\n✅ Timeline correctly integrated into Agent context.")
    else:
        print("\n❌ Timeline missing from Agent context.")

if __name__ == "__main__":
    asyncio.run(verify_timeline())
