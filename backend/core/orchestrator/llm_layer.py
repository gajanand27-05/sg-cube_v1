import json
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from backend.ai_modules.llm.ollama_client import OllamaError, generate

SYSTEM_PROMPT = """You are an intent-parser for SG_CUBE, a local AI Operating System.
Convert the user's natural-language command into a JSON object with this exact shape:
{
  "action": "<action_name>",
  "target": "<target_or_empty_string>",
  "args": {}
}

Valid actions:
- open_app   : open a desktop application. target is the app name. ANY installed app is valid (notepad, chrome, firefox, spotify, discord, whatsapp, vscode, vlc, etc.).
- close_app  : close a desktop application. target is the app name.
- get_time   : return the current time. target is empty.
- unknown    : the input does not match any known action.

Examples:
User: "open notepad"          -> {"action":"open_app","target":"notepad","args":{}}
User: "launch chrome"         -> {"action":"open_app","target":"chrome","args":{}}
User: "start firefox"         -> {"action":"open_app","target":"firefox","args":{}}
User: "open spotify"          -> {"action":"open_app","target":"spotify","args":{}}
User: "launch discord"        -> {"action":"open_app","target":"discord","args":{}}
User: "open whatsapp"         -> {"action":"open_app","target":"whatsapp","args":{}}
User: "open vscode"           -> {"action":"open_app","target":"vscode","args":{}}
User: "open visual studio code" -> {"action":"open_app","target":"vscode","args":{}}
User: "close calculator"      -> {"action":"close_app","target":"calc","args":{}}
User: "quit spotify"          -> {"action":"close_app","target":"spotify","args":{}}
User: "what time is it"       -> {"action":"get_time","target":"","args":{}}
User: "tell me a joke"        -> {"action":"unknown","target":"","args":{}}
User: "play some music"       -> {"action":"unknown","target":"","args":{}}

Rules:
- Output ONLY the JSON object. No commentary, no markdown fences.
- Always include all three keys: action, target, args.
- If the user is asking to open or close an app and you can identify its name, USE open_app/close_app — don't fall back to unknown just because the app isn't in the examples.
- If unsure or the request isn't an app action or time query, use "unknown".
- Use lowercase for `target` and drop adjectives like "the" or "my".
"""


class Intent(BaseModel):
    action: str
    target: str = ""
    args: dict[str, Any] = Field(default_factory=dict)


class LLMResolveError(RuntimeError):
    pass


def resolve(text: str, retries: int = 1) -> Intent:
    """Convert natural-language input into an Intent via Ollama.

    Calls Ollama with format=json so the response is guaranteed to be JSON.
    On parse/validation failure, retries up to `retries` more times.
    Raises LLMResolveError if all attempts fail or Ollama is unreachable.
    """
    last_err: Exception | None = None
    for _ in range(retries + 1):
        try:
            raw = generate(text, system=SYSTEM_PROMPT, json_mode=True)
        except OllamaError as e:
            raise LLMResolveError(str(e)) from e

        try:
            data = json.loads(raw)
            return Intent(**data)
        except (json.JSONDecodeError, ValidationError, TypeError) as e:
            last_err = e

    raise LLMResolveError(
        f"LLM did not return valid intent JSON after {retries + 1} attempts: {last_err}"
    )
