import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.core.observability import engine as obs_engine
from backend.core.events import bus
from backend.daemon.ui_events import ConfidenceEvent

async def verify_metrics():
    print("── RELIABILITY METRICS VERIFICATION ────────────────")
    
    received_event = None
    def on_event(e):
        nonlocal received_event
        received_event = e

    bus.subscribe(ConfidenceEvent, on_event)
    
    # 1. Report some data
    rid = "test-metrics"
    print("Reporting tool success, memory match, and hallucination check...")
    obs_engine.report_tool_quality(rid, 100.0, "Success")
    obs_engine.report_context_quality(rid, 91.0, "Memory found")
    obs_engine.report_ai_quality(rid, 100.0, "No hallucination") # This counts as 1 check
    obs_engine.report_latency(rid, 1200) # 1.2s
    
    # Wait for event propagation
    await asyncio.sleep(0.1)
    
    if received_event:
        m = received_event.metrics
        print(f"\nCaptured Metrics:")
        print(f"Tool Success: {m.tool_success_rate}% (Expected: 100.0%)")
        print(f"Avg Response: {m.avg_response_sec}s (Expected: 1.2s)")
        print(f"Memory Recall: {m.memory_recall_pct}% (Expected: 91.0%)")
        print(f"Hallucination: {m.hallucination_passed}/{m.hallucination_total} (Expected: 1/1)")
        
        if (m.tool_success_rate == 100.0 and 
            m.avg_response_sec == 1.2 and 
            m.memory_recall_pct == 91.0 and 
            m.hallucination_passed == 1):
            print("\n✅ Reliability metrics correctly calculated and reported.")
        else:
            print("\n❌ Metric calculation mismatch.")
    else:
        print("\n❌ No ConfidenceEvent received.")

if __name__ == "__main__":
    asyncio.run(verify_metrics())
