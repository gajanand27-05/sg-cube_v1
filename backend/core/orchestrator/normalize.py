import re
import string

_punct_table = str.maketrans("", "", string.punctuation)
_whitespace = re.compile(r"\s+")

# Trailing sentence punctuation and surrounding quotes are safe to drop for
# rule matching; everything else must survive.
_trailing_punct = re.compile(r"[.?!]+$")
_surrounding_quotes = re.compile(r"^[\"'`]+|[\"'`]+$")


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
