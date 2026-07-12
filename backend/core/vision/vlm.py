import json
import logging
from typing import Any, Optional

from backend.ai_modules.llm.ollama_client import generate as ollama_generate
from backend.server.config import settings

log = logging.getLogger(__name__)

VLM_SYSTEM_PROMPT = """Analyze the provided screenshot and focused window title.
Respond ONLY with a JSON object in this format:
{
  "app": "Application Name",
  "summary": "One sentence describing exactly what the user is doing or looking at.",
  "keywords": ["tag1", "tag2", "tag3"],
  "objects": [{"label": "person", "confidence": 0.98}],
  "ocr": ["STOP", "Main Street"]
}

Be specific. If code is visible, mention the language. If a website is open, mention the domain.
"objects" lists notable things visible (people, vehicles, UI elements) each with a 0-1 confidence.
"ocr" lists short text strings readable on screen.
"""

async def analyze_screenshot(image_b64: str, window_title: str) -> Optional[dict]:
    """Use a local VLM to summarize the screenshot."""
    prompt = f"Focused Window: {window_title}\n\nWhat is on the screen?"
    
    try:
        response = await ollama_generate(
            prompt=prompt,
            system=VLM_SYSTEM_PROMPT,
            images=[image_b64],
            model=settings.vision_model,
            json_mode=True,
            timeout=120.0 # Vision models take longer
        )
        
        data = json.loads(response)
        # Ensure it has the right fields
        if "app" not in data: data["app"] = window_title
        if "summary" not in data: data["summary"] = "User looking at screen."
        if "keywords" not in data: data["keywords"] = []
        if "objects" not in data: data["objects"] = []
        if "ocr" not in data: data["ocr"] = []

        return data
        
    except Exception as e:
        log.error(f"VLM analysis failed: {e}")
        return None
