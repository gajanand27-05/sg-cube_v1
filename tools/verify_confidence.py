import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.core.tools.registry import ToolResult, ToolStatus
from backend.core.runtime import runtime

async def verify_tool_confidence():
    print("── TOOL CONFIDENCE VERIFICATION ────────────────")
    
    # Import tools to ensure they are registered
    from backend.core.tools import summarize, weather, ocr, registry
    
    # 1. Test summarize_pdf (will fail to find file, but check error structure)
    print("Testing summarize_pdf structure...")
    res = await registry.REGISTRY["summarize_pdf"](file="nonexistent.pdf")
    print(f"Status: {res.status}")
    print(f"Confidence: {res.confidence}%")
    print(f"Reason: {res.confidence_reason}")
    
    if hasattr(res, 'confidence') and isinstance(res.confidence_reason, list):
        print("✅ summarize_pdf returns ToolResult with confidence fields.")
    else:
        print("❌ summarize_pdf missing confidence fields.")

    # 2. Test weather (should work if Mumbai is default)
    print("\nTesting get_weather structure...")
    res = await registry.REGISTRY["get_weather"](location="Mumbai")
    print(f"Status: {res.status}")
    print(f"Confidence: {res.confidence}%")
    print(f"Reason: {res.confidence_reason}")
    
    if res.confidence > 0 and len(res.confidence_reason) > 0:
        print("✅ get_weather returns rich confidence data.")
    else:
        print("❌ get_weather missing rich confidence data.")

    # 3. Test legacy tool coercion in runtime
    print("\nTesting legacy tool coercion...")
    # Define a dummy legacy tool function
    def legacy_tool():
        return {"status": "success", "message": "hello"}
    
    # Wrap it in the runtime call logic (simulated)
    # We use a tool that still returns dict for this test
    from backend.core.tools import system_info, registry
    result = await registry.REGISTRY["get_system_status"]()
    
    # The registry __call__ uses runtime.run_tool
    # If get_system_info still returns a dict, it will be coerced
    print(f"Legacy result type: {type(result)}")
    print(f"Coerced Confidence: {result.confidence}%")
    
    if result.confidence == 100.0:
        print("✅ Runtime correctly coerced legacy dict to 100% confidence.")
    else:
        print(f"❌ Coercion failed or confidence is unexpected: {result.confidence}")

if __name__ == "__main__":
    asyncio.run(verify_tool_confidence())
