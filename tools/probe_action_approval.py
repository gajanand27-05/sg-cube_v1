import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.core.agents.guardian import GuardianAgent
from backend.core.agent.context import ConversationContext

async def test_approval_levels():
    print("── ACTION APPROVAL LEVELS VERIFICATION ────────────────")
    
    # Import builtins to register all tools
    from backend.core.tools import builtins, registry
    
    # Debug: check security level of shutdown_pc
    if "shutdown_pc" in registry.REGISTRY:
        t = registry.REGISTRY['shutdown_pc']
        print(f"DEBUG: shutdown_pc object = {t}")
        print(f"DEBUG: shutdown_pc security = {t.security} (type: {type(t.security)})")
        print(f"DEBUG: SecurityLevel.CRITICAL = {registry.SecurityLevel.CRITICAL}")
        print(f"DEBUG: Match? {t.security == registry.SecurityLevel.CRITICAL}")
    else:
        print("DEBUG: shutdown_pc NOT in registry")

    guardian = GuardianAgent()
    request_id = "test-req"

    # 1. Test SAFE Action (e.g., get_time, find_file)
    print("\nTesting SAFE action (find_file)...")
    calls_safe = [{"name": "find_file", "args": {"query": "test"}, "confidence": 0.9, "reasoning": "User wants to find a file."}]
    valid, pending, errors = guardian.verify_plan("find my test file", calls_safe, request_id)
    print(f"Valid: {len(valid)}, Pending: {len(pending)}, Errors: {len(errors)}")
    if len(valid) == 1 and not pending:
        print("✅ SAFE action correctly passed without confirmation.")
    else:
        print("❌ SAFE action failed verification.")

    # 2. Test CAUTION Action (e.g., delete_file, send_email)
    print("\nTesting CAUTION action (delete_file)...")
    calls_caution = [{"name": "delete_file", "args": {"file": "trash.txt"}, "confidence": 0.9, "reasoning": "User wants to delete a file."}]
    valid, pending, errors = guardian.verify_plan("delete trash.txt", calls_caution, request_id)
    print(f"Valid: {len(valid)}, Pending: {len(pending)}, Errors: {len(errors)}")
    if not valid and len(pending) == 1:
        print("✅ CAUTION action correctly flagged for confirmation.")
        if pending[0].get("needs_confirmation") and not pending[0].get("is_critical"):
            print("   Flags: needs_confirmation=True, is_critical=False")
    else:
        print("❌ CAUTION action failed verification.")

    # 3. Test CRITICAL Action (e.g., shutdown_pc)
    print("\nTesting CRITICAL action (shutdown_pc)...")
    calls_critical = [{"name": "shutdown_pc", "args": {}, "confidence": 1.0, "reasoning": "User wants to turn off the PC."}]
    valid, pending, errors = guardian.verify_plan("shutdown now", calls_critical, request_id)
    print(f"Valid: {len(valid)}, Pending: {len(pending)}, Errors: {len(errors)}")
    if not valid and len(pending) == 1:
        print("✅ CRITICAL action correctly flagged for confirmation.")
        if pending[0].get("needs_confirmation") and pending[0].get("is_critical"):
            print("   Flags: needs_confirmation=True, is_critical=True")
    else:
        print("❌ CRITICAL action failed verification.")

if __name__ == "__main__":
    asyncio.run(test_approval_levels())
