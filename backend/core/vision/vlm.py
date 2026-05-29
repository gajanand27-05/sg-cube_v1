import json
import logging
from typing import Any, Optional

from backend.ai_modules.llm import ollama_client
from backend.server.config import settings

log = logging.getLogger(__name__)

VLM_SYSTEM_PROMPT = """Analyze the provided screenshot and focused window title.
Respond ONLY with a JSON object in this format:
{
  "app": "Application Name",
  "summary": "One sentence describing exactly what the user is doing or looking at.",
  "keywords": ["tag1", "tag2", "tag3"]
}

Be specific. If code is visible, mention the language. If a website is open, mention the domain.
"""

async def analyze_screenshot(image_b64: str, window_title: str) -> Optional[dict]:
    """Use a local VLM to summarize the screenshot."""
    prompt = f"Focused Window: {window_title}\n\nWhat is on the screen?"
    
    try:
        response = ollama_client.generate(
            prompt=prompt,
            system=VLM_SYSTEM_PROMPT,
            images=[image_b64],
            model=settings.vlm_model,
            json_mode=True,
            timeout=120.0 # Vision models take longer
        )
        
        data = json.loads(response)
        # Ensure it has the right fields
        if "app" not in data: data["app"] = window_title
        if "summary" not in data: data["summary"] = "User looking at screen."
        if "keywords" not in data: data["keywords"] = []
        
        return data
        
    except Exception as e:
        log.error(f"VLM analysis failed: {e}")
        return None
