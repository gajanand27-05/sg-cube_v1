import sys
import asyncio
import numpy as np
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.daemon.trigger import _handle_wake_async

async def test_trigger_logic():
    print("── TRIGGER ENERGY VERIFICATION ────────────────")
    
    # Generate 1 second of near-silence (RMS well below 200)
    silent_audio = np.zeros(16000, dtype=np.int16).tobytes()
    
    print("Testing trigger with silent audio...")
    # This should return False and transition to IDLE without calling Whisper
    result = await _handle_wake_async(silent_audio)
    
    if result is False:
        print("✅ Trigger correctly rejected near-silent audio.")
    else:
        print("❌ Trigger unexpectedly accepted silent audio.")

if __name__ == "__main__":
    asyncio.run(test_trigger_logic())
