import asyncio
import sys
import time
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.core.agents.watcher import watcher
from backend.core.events import bus
from backend.daemon.ui_events import ProactiveEvent
import threading

def test_watcher():
    print("── AUTONOMOUS WATCHER VERIFICATION ────────────────")
    
    received_event = None
    
    def on_event(e):
        nonlocal received_event
        received_event = e
        print(f"Captured ProactiveEvent: {e.query}")
        
    bus.subscribe(ProactiveEvent, on_event)
    
    print("Starting watcher...")
    watcher.start()
    
    # We create a dummy test task type just for verification
    print("Injecting dummy test task...")
    watcher.tasks.append({
        "type": "test_dummy",
        "action": "Tell me it works"
    })
    
    # Monkeypatch the check_task to handle our dummy
    original_check = watcher._check_task
    def mock_check(t):
        if t["type"] == "test_dummy":
            watcher._fire(t["action"] + " (Context: Test passed)")
        else:
            original_check(t)
    watcher._check_task = mock_check
    
    # Wait for the loop to poll (it polls every 5s, so we wait up to 6s)
    time.sleep(6)
    
    if received_event:
        print("✅ Watcher successfully fired a proactive event from the background thread.")
    else:
        print("❌ No event fired within 1 second.")
        
    watcher.stop()

if __name__ == "__main__":
    test_watcher()
