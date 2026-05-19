"""Translation tool (Phase 11e) — uses gemma4 as the translator.

No external API; the same Ollama model that does reasoning handles the
translation. Quality is good for common language pairs.
"""
from backend.core.tools.llm_helper import llm_generate
from backend.core.tools.registry import tool

# Common alias -> canonical name (so the LLM sees something consistent).
LANG_ALIASES = {
    "en": "English", "english": "English",
    "es": "Spanish", "spanish": "Spanish",
    "fr": "French", "french": "French",
    "de": "German", "german": "German",
    "it": "Italian", "italian": "Italian",
    "pt": "Portuguese", "portuguese": "Portuguese",
    "ru": "Russian", "russian": "Russian",
    "zh": "Chinese", "chinese": "Chinese", "mandarin": "Chinese",
    "ja": "Japanese", "japanese": "Japanese",
    "ko": "Korean", "korean": "Korean",
    "ar": "Arabic", "arabic": "Arabic",
    "hi": "Hindi", "hindi": "Hindi",
    "ta": "Tamil", "tamil": "Tamil",
    "te": "Telugu", "telugu": "Telugu",
    "bn": "Bengali", "bengali": "Bengali",
    "tr": "Turkish", "turkish": "Turkish",
    "nl": "Dutch", "dutch": "Dutch",
    "pl": "Polish", "polish": "Polish",
    "sv": "Swedish", "swedish": "Swedish",
    "vi": "Vietnamese", "vietnamese": "Vietnamese",
    "th": "Thai", "thai": "Thai",
    "id": "Indonesian", "indonesian": "Indonesian",
    "ur": "Urdu", "urdu": "Urdu",
}

TRANSLATE_SYSTEM = (
    "You are a translator. Output ONLY the translated text. No preface, no "
    "quotes, no notes about meaning, no language labels. If the input is "
    "already in the target language, return it unchanged."
)


@tool
def translate(text: str, target_language: str = "English") -> dict:
    """Translate `text` to `target_language`. Common names and ISO codes work:
    "Spanish"/"es", "Hindi"/"hi", "French"/"fr", "Japanese"/"ja", etc."""
    text = (text or "").strip()
    if not text:
        return {"status": "blocked", "reason": "empty text"}

    tl = target_language.strip().lower()
    target = LANG_ALIASES.get(tl, target_language.strip().title() or "English")

    out = llm_generate(
        f"Translate the following text to {target}:\n\n{text}",
        system=TRANSLATE_SYSTEM,
        temperature=0.1,
    )
    if not out:
        return {"status": "error", "reason": "translation model returned nothing"}

    return {
        "status": "success",
        "message": out,
        "args": {"target_language": target, "source_chars": len(text)},
    }
