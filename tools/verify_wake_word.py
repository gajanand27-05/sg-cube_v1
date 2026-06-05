import sys
from pathlib import Path
import json

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.daemon.wake_word import WakeWordListener

def verify_onyx():
    print("── WAKE WORD VERIFICATION ────────────────")
    
    # Initialize listener (without real mic if possible, or just check attributes)
    try:
        # We don't start the listener, just check its configuration
        listener = WakeWordListener(
            on_wake=lambda x: None,
            wake_phrase="onyx"
        )
        
        print(f"Target Phrase: {listener.wake_phrase}")
        
        # Access the recognizer to see what it's listening for
        # Vosk recognizer doesn't expose the grammar easily, but we can check the init args
        if listener.wake_phrase == "onyx":
            print("✅ Internal wake_phrase correctly set to 'onyx'.")
        else:
            print(f"❌ Internal wake_phrase is '{listener.wake_phrase}', expected 'onyx'.")

    except Exception as e:
        print(f"❌ Error during initialization: {e}")

if __name__ == "__main__":
    verify_onyx()
