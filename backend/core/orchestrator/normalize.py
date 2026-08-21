import re
import string

_punct_table = str.maketrans("", "", string.punctuation)
_whitespace = re.compile(r"\s+")

# Trailing sentence punctuation and surrounding quotes are safe to drop for
# rule matching; everything else must survive.
_trailing_punct = re.compile(r"[.?!]+$")
_surrounding_quotes = re.compile(r"^[\"'`]+|[\"'`]+$")


# A leading wake phrase, with the punctuation Whisper puts after it. Optional
# "hey"/"ok" because people say them and Whisper transcribes them.
_wake_prefix = re.compile(
    r"^\s*(?:hey\s+|ok(?:ay)?\s+)?onyx\b[\s,.:;!?—–-]*", re.IGNORECASE)


def strip_wake_prefix(text: str, _pattern: re.Pattern = _wake_prefix) -> str:
    """Remove a leading wake phrase so the router can see the command.

    Every rule pattern is anchored with ^, and the captured audio starts with
    the wake word (the pre-roll includes it deliberately). So:

        "close chrome"        -> close_app:'chrome'   0.1ms, actually closes
        "Onyx, close chrome." -> no rule -> planner   1748ms, says "Done."

    That "Done." with zero tools is indistinguishable from success, which is
    what makes this worse than an error. Priming Whisper for the name stopped
    it fusing into the next word and, in doing so, made the wake word appear
    cleanly at the front of every command — turning a garbled-transcript bug
    into a universal routing miss.

    Only the FRONT, and only once: "what is onyx 130" is a question about
    onyx, and a bare "Onyx" is someone getting attention rather than a command
    with the name removed — stripping that to "" would hide it from the
    content gate that is supposed to reject it.
    """
    if not text:
        return ""
    stripped = _pattern.sub("", text, count=1)
    return stripped if stripped.strip() else text


def normalize(text: str) -> str:
    """Cache-key normalizer: lowercase, drop punctuation, collapse whitespace.

    "Open Notepad."   -> "open notepad"
    "what time is it?" -> "what time is it"
    "  CLOSE  Chrome " -> "close chrome"

    Only suitable for cache keys, where dropping punctuation widens fuzzy
    matching. Use normalize_for_rules() for the rule engine — this one
    destroys arithmetic operators and URL structure.
    """
    text = text.strip().lower().translate(_punct_table)
    return _whitespace.sub(" ", text).strip()


def normalize_for_rules(text: str) -> str:
    """Rule-engine normalizer: lowercase and tidy, but keep the characters
    rules actually match on.

    normalize() strips all of string.punctuation, which silently destroys the
    operators and dots that the calculator and URL rules require — those rules
    could never fire against its output. This keeps `+ - * / % . : /` intact
    and removes only what is noise for matching.

    "Calculate 2+2."          -> "calculate 2+2"
    "Open GitHub.com"          -> "open github.com"
    "what time is it?"         -> "what time is it"
    '"take a screenshot"'      -> "take a screenshot"
    """
    text = _surrounding_quotes.sub("", text.strip()).strip()
    text = _trailing_punct.sub("", text).strip()
    return _whitespace.sub(" ", text.lower()).strip()
