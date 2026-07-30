"""Pull speakable prose out of the Planner's JSON envelope, incrementally.

Phase 4B streams the Planner's tokens straight to TTS, one sentence at a time,
to cut time-to-first-audio. That assumed the token stream is prose. It is not —
the Planner emits a serialized envelope:

    {"final_response": "Got it! Jupiter is the largest planet."}

so the sentence-boundary predicate tripped on punctuation *inside the JSON* and
Piper spoke `{"final_response":"Got it!` out loud, on every streaming turn.

The mismatch is the envelope, so this is where it gets resolved: feed raw tokens
in, get only the characters of the `final_response` value out. A tool_calls
envelope yields nothing, which is correct — those turns speak after execution.

Deliberately not a JSON parser. It cannot wait for a complete document without
giving back the entire Phase 4B win, so it is a character state machine that
starts emitting the moment the opening quote of the value arrives.
"""
import re

# Matches the key, its colon and the opening quote of the value, tolerating
# whitespace anywhere the JSON spec allows it. Anything before it (a ```json
# fence, or a model that prefixed prose) is skipped.
_VALUE_START = re.compile(r'"final_response"\s*:\s*"')

# The pattern is short and its parts are adjacent, so a small sliding tail is
# enough to survive it being split across token boundaries. Bounds memory on a
# long tool_calls envelope, which never matches at all.
_SCAN_TAIL = 256

_SIMPLE_ESCAPES = {
    '"': '"', "\\": "\\", "/": "/",
    "b": "\b", "f": "\f", "n": "\n", "r": "\r", "t": "\t",
}


class FinalResponseExtractor:
    """Streams the value of `final_response` out of a JSON token stream.

    Stateful and single-use per generation attempt. `feed()` returns whatever
    prose became available from that delta — often "", sometimes a fragment of
    a word, since token boundaries respect nothing.
    """

    def __init__(self) -> None:
        self._scan = ""                    # pre-value text, dropped once matched
        self._in_value = False
        self._done = False
        self._escape = False               # previous char was a backslash
        self._unicode: str | None = None   # not None => collecting \uXXXX digits
        self._started = False

    @property
    def done(self) -> bool:
        """The closing quote arrived — no further prose is coming."""
        return self._done

    @property
    def started(self) -> bool:
        """The value was found and emission has begun."""
        return self._started

    def feed(self, delta: str) -> str:
        """Consume one token; return whatever prose it completed."""
        if self._done or not delta:
            return ""

        if not self._in_value:
            self._scan += delta
            match = _VALUE_START.search(self._scan)
            if match is None:
                if len(self._scan) > _SCAN_TAIL:
                    self._scan = self._scan[-_SCAN_TAIL:]
                return ""
            self._in_value = True
            self._started = True
            remainder = self._scan[match.end():]
            self._scan = ""
            return self._consume(remainder)

        return self._consume(delta)

    def _consume(self, text: str) -> str:
        out: list[str] = []
        for ch in text:
            # \uXXXX arrives up to four tokens late; hold until complete.
            if self._unicode is not None:
                self._unicode += ch
                if len(self._unicode) == 4:
                    out.append(self._decode_unicode(self._unicode))
                    self._unicode = None
                continue

            if self._escape:
                self._escape = False
                if ch == "u":
                    self._unicode = ""
                else:
                    out.append(_SIMPLE_ESCAPES.get(ch, ch))
                continue

            if ch == "\\":
                self._escape = True
                continue

            if ch == '"':
                self._done = True
                break

            out.append(ch)

        return "".join(out)

    @staticmethod
    def _decode_unicode(digits: str) -> str:
        try:
            code = int(digits, 16)
        except ValueError:
            # Malformed — emit it literally rather than swallow the sentence.
            return "\\u" + digits
        if 0xD800 <= code <= 0xDFFF:
            # Half of a surrogate pair (an emoji, usually). Emitting a lone
            # surrogate would raise on the next UTF-8 encode and take a log
            # handler down with it — the exact class of bug as T-log-cp1252.
            # Nothing is lost for speech: Piper does not pronounce emoji.
            return ""
        return chr(code)
