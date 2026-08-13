import sys
import wave
import numpy as np
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.ai_modules.speech.stt_whisper import transcribe

def create_test_audio(filename, duration=2.0, type='silence'):
    path = Path(filename)
    rate = 16000
    n_samples = int(rate * duration)
    
    if type == 'silence':
        data = np.zeros(n_samples, dtype=np.int16)
    elif type == 'white_noise':
        # Low amplitude white noise (static)
        data = (np.random.randn(n_samples) * 100).astype(np.int16)
    
    with wave.open(str(path), 'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(data.tobytes())
    return path

def test_robustness():
    print("── WHISPER NOISE ROBUSTNESS TEST ────────────────")
    
    # Test 1: Absolute Silence
    silence_path = create_test_audio("test_silence.wav", type='silence')
    print(f"Testing absolute silence...")
    res_silence = transcribe(silence_path)
    text_silence = res_silence['text']
    if not text_silence:
        print("✅ Silence correctly resulted in empty string.")
    else:
        print(f"❌ Silence resulted in unexpected text: '{text_silence}'")
        
    # Test 2: Low-level Static (White Noise)
    noise_path = create_test_audio("test_noise.wav", type='white_noise')
    print(f"Testing background static...")
    res_noise = transcribe(noise_path)
    text_noise = res_noise['text']
    if not text_noise:
        print("✅ Static correctly filtered out (empty string).")
    else:
        # Check if it hit the "Thank you" hallucination
        print(f"❌ Static resulted in text: '{text_noise}'")
        print(f"   Logprob: {res_noise.get('avg_logprob', 'N/A')}")

    # Cleanup
    silence_path.unlink()
    noise_path.unlink()

if __name__ == "__main__":
    try:
        test_robustness()
    except Exception as e:
        print(f"Test failed with error: {e}")
