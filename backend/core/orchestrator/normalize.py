import re
import string

_punct_table = str.maketrans("", "", string.punctuation)
_whitespace = re.compile(r"\s+")


def normalize(text: str) -> str:
    """Cache-key normalizer: lowercase, drop punctuation, collapse whitespace.

    "Open Notepad."   -> "open notepad"
    "what time is it?" -> "what time is it"
    "  CLOSE  Chrome " -> "close chrome"
    """
    text = text.strip().lower().translate(_punct_table)
    return _whitespace.sub(" ", text).strip()
