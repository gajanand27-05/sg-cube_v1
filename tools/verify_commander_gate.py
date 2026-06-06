import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.core.agents.commander import commander
from backend.core.agent.context import ConversationContext
from backend.core.tools import builtins

async def test_commander_gate():
    print("── COMMANDER GATE VERIFICATION ────────────────")
    ctx = ConversationContext()
    
    # Mock the planner and verifier
    original_generate = commander.planner.generate_plan
    import backend.core.agents.guardian as guardian_mod
    original_verify = guardian_mod.verify_call
    
    # Mock 1: CAUTION
    print("\n[TEST 1] Simulating CAUTION: 'Delete test.txt'")
    async def mock_gen_caution(text, history, memory):
        return [{"name": "delete_file", "args": {"file": "test.txt"}}]
    
    def mock_verify_caution(query, call, **kwargs):
        from backend.core.agent.verifier import VerificationResult
        return VerificationResult(True, needs_confirmation=True, is_critical=False)

    commander.planner.generate_plan = mock_gen_caution
    guardian_mod.verify_call = mock_verify_caution
    
    try:
        response, _ = await commander.run("delete test.txt", ctx)
        print(f"ONYX: {response}")
        if "permission" in response and "delete file" in response:
            print("✅ CAUTION Gate Passed.")
        else:
            print("❌ CAUTION Gate Failed.")
    except Exception as e: print(f"Error: {e}")

    # Mock 2: CRITICAL
    print("\n[TEST 2] Simulating CRITICAL: 'Shutdown PC'")
    async def mock_gen_critical(text, history, memory):
        return [{"name": "shutdown_pc", "args": {}}]
    
    def mock_verify_critical(query, call, **kwargs):
        from backend.core.agent.verifier import VerificationResult
        return VerificationResult(True, needs_confirmation=True, is_critical=True)

    commander.planner.generate_plan = mock_gen_critical
    guardian_mod.verify_call = mock_verify_critical
    
    try:
        response, _ = await commander.run("shutdown pc", ctx)
        print(f"ONYX: {response}")
        if "CRITICAL ACTION" in response and "shutdown pc" in response:
            print("✅ CRITICAL Gate Passed.")
        else:
            print("❌ CRITICAL Gate Failed.")
    finally:
        # Restore originals
        commander.planner.generate_plan = original_generate
        guardian_mod.verify_call = original_verify

if __name__ == "__main__":
    # We need to ensure LLM is available for this real run
    asyncio.run(test_commander_gate())
