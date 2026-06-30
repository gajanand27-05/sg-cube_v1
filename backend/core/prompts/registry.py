"""Prompt Registry — versioned prompt templates with git-like history."""
import hashlib
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

log = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).resolve().parents[2] / "core" / "prompts"


class PromptVersion:
    """Single version of a prompt template."""
    def __init__(self, name: str, version: int, content: str, metadata: dict = None):
        self.name = name
        self.version = version
        self.content = content
        self.metadata = metadata or {}
        self.hash = hashlib.sha256(content.encode()).hexdigest()[:12]
        self.created_at = datetime.now().isoformat()
    
    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "version": self.version,
            "content": self.content,
            "metadata": self.metadata,
            "hash": self.hash,
            "created_at": self.created_at,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "PromptVersion":
        pv = cls(data["name"], data["version"], data["content"], data.get("metadata", {}))
        pv.hash = data.get("hash", pv.hash)
        pv.created_at = data.get("created_at", pv.created_at)
        return pv


class PromptRegistry:
    """Manages versioned prompt templates."""
    
    def __init__(self, prompts_dir: Path = PROMPTS_DIR):
        self.prompts_dir = prompts_dir
        self.prompts_dir.mkdir(parents=True, exist_ok=True)
        self._cache: dict[str, list[PromptVersion]] = {}
    
    def get_latest(self, name: str) -> PromptVersion | None:
        """Get the latest version of a prompt."""
        versions = self.get_all_versions(name)
        return versions[-1] if versions else None
    
    def get_version(self, name: str, version: int) -> PromptVersion | None:
        """Get a specific version of a prompt."""
        versions = self.get_all_versions(name)
        for v in versions:
            if v.version == version:
                return v
        return None
    
    def get_all_versions(self, name: str) -> list[PromptVersion]:
        """Get all versions of a prompt (cached)."""
        if name not in self._cache:
            self._load_prompt(name)
        return self._cache.get(name, [])
    
    def _load_prompt(self, name: str) -> None:
        """Load all versions of a prompt from disk."""
        prompt_file = self.prompts_dir / f"{name}.yaml"
        if not prompt_file.exists():
            self._cache[name] = []
            return
        
        with open(prompt_file) as f:
            data = yaml.safe_load(f)
        
        versions = []
        for v_data in data.get("versions", []):
            versions.append(PromptVersion.from_dict(v_data))
        versions.sort(key=lambda v: v.version)
        self._cache[name] = versions
    
    def save_version(self, name: str, content: str, metadata: dict = None, author: str = "system") -> PromptVersion:
        """Create a new version of a prompt."""
        versions = self.get_all_versions(name)
        new_version = len(versions) + 1
        
        pv = PromptVersion(name, new_version, content, metadata or {})
        pv.metadata["author"] = author
        versions.append(pv)
        
        # Save to disk
        prompt_file = self.prompts_dir / f"{name}.yaml"
        data = {
            "name": name,
            "versions": [v.to_dict() for v in versions],
        }
        with open(prompt_file, "w") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)
        
        log.info(f"Saved prompt {name} v{new_version} (hash: {pv.hash})")
        return pv
    
    def render(self, name: str, version: int | None = None, **kwargs) -> str:
        """Render a prompt with variables."""
        pv = self.get_version(name, version) if version else self.get_latest(name)
        if not pv:
            raise ValueError(f"Prompt not found: {name} v{version or 'latest'}")
        return pv.content.format(**kwargs)
    
    def diff(self, name: str, v1: int, v2: int) -> dict:
        """Show diff between two versions."""
        pv1 = self.get_version(name, v1)
        pv2 = self.get_version(name, v2)
        if not pv1 or not pv2:
            raise ValueError(f"Version not found: {name} v{v1} or v{v2}")
        
        # Simple line-by-line diff
        lines1 = pv1.content.splitlines()
        lines2 = pv2.content.splitlines()
        
        diff = []
        max_len = max(len(lines1), len(lines2))
        for i in range(max_len):
            l1 = lines1[i] if i < len(lines1) else None
            l2 = lines2[i] if i < len(lines2) else None
            if l1 != l2:
                diff.append({
                    "line": i + 1,
                    "v1": l1,
                    "v2": l2,
                })
        
        return {
            "prompt": name,
            "v1": v1,
            "v2": v2,
            "hash_v1": pv1.hash,
            "hash_v2": pv2.hash,
            "diff": diff,
        }


# Global instance
prompt_registry = PromptRegistry()


# Default prompts to initialize
DEFAULT_PROMPTS = {
    "planner": {
        "content": """You are the PLANNER Agent for SG_CUBE.
Available capabilities:
{caps}
{profile_hint}
{memory_context}

Output ONLY a JSON object with:
{{"tool_calls": [{{"name": "capability", "args": {{...}}, "confidence": 0.0-1.0, "reasoning": "..."}}]}}
If no action is needed, return {{"final_response": "..."}}.""",
        "metadata": {"description": "Planner agent system prompt"},
    },
    "verifier": {
        "content": """You are a safety and logic verifier for an AI Operating System.
User Query: "{user_query}"
Proposed Action: Call tool "{tool_name}" with arguments {tool_args}
LLM Reasoning: "{reasoning}"

Is this action logically sound, safe, and directly relevant to the user's query?
Reply with a single JSON object: {{"verified": true}} or {{"verified": false, "reason": "..."}}""",
        "metadata": {"description": "Guardian verifier prompt"},
    },
    "intent_classifier": {
        "content": """You are an intent-parser for SG_CUBE, a local AI Operating System.
Convert the user's natural-language command into a JSON object with this exact shape:
{{
  "action": "<action_name>",
  "target": "<target_or_empty_string>",
  "args": {{}}
}}

Valid actions:
- open_app        : open a desktop application
- close_app       : close a desktop application
- get_time        : return the current time
- open_url        : open a URL or website
- search_google   : open Google search results
- search_youtube  : open YouTube search results
- play_youtube    : play the first matching YouTube video
- unknown         : the input does not match any known action

Rules:
- Output ONLY the JSON object. No commentary, no markdown fences.
- "play X" always means play_youtube — the user wants media to start playing.
- If unsure, use "unknown".""",
        "metadata": {"description": "Intent classifier prompt"},
    },
    "episodic_summarizer": {
        "content": """Analyze this AI-User interaction.
User Query: "{user_query}"
Actions Taken: {interactions}

Extract two things:
1. NEW FACTS: Any persistent info about the user (names, dates, preferences).
2. SUCCESSFUL PATTERN: If a specific tool sequence worked well, summarize the 'workflow'.

Reply with a single JSON object:
{{
  "facts": ["..."],
  "patterns": ["..."]
}}""",
        "metadata": {"description": "Episodic summarizer prompt"},
    },
}


def initialize_default_prompts():
    """Initialize default prompts if they don't exist."""
    for name, data in DEFAULT_PROMPTS.items():
        if not prompt_registry.get_latest(name):
            prompt_registry.save_version(name, data["content"], data.get("metadata", {}))
            log.info(f"Initialized default prompt: {name}")


if __name__ == "__main__":
    initialize_default_prompts()