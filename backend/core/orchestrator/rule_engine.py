import re
from typing import Callable

from backend.core.orchestrator.llm_layer import Intent

# ── Phase D3: Expanded APP_ALIASES (30 → 100+) ─────────────────────────
APP_ALIASES = {
    # ── Built-in Windows ──
    "calculator": "calc",
    "calc": "calc",
    "notepad": "notepad",
    "text editor": "notepad",
    "explorer": "explorer",
    "file explorer": "explorer",
    "files": "explorer",
    "this pc": "explorer",
    "my computer": "explorer",
    "control panel": "control",
    "settings": "ms-settings",
    "taskbar settings": "ms-settings:taskbar",
    "snipping tool": "snippingtool",
    "snip and sketch": "snippingtool",
    "paint": "mspaint",
    "wordpad": "wordpad",
    "sticky notes": "stikynot",
    "alarms": "ms-clock",
    "clock": "ms-clock",
    "camera": "windows+camera",
    "voice recorder": "ms-voice recorder",
    "calculator": "calc",
    "calendar": "outlookcal",
    "mail": "outlookmail",
    "maps": "bingmaps",
    "news": "ms-news",
    "sports": "ms-sports",
    "weather": "msnweather",
    "xbox": "xboxapp",
    "terminal": "wt",
    "windows terminal": "wt",
    "registry editor": "regedit",
    "regedit": "regedit",
    "task manager": "taskmgr",
    "resource monitor": "resmon",
    "performance monitor": "perfmon",
    "disk cleanup": "cleanmgr",
    "defragment": "dfrgui",
    "event viewer": "eventvwr",
    "services": "services.msc",
    "group policy": "gpedit.msc",
    "device manager": "devmgmt.msc",
    "computer management": "compmgmt.msc",
    "disk management": "diskmgmt.msc",
    "command prompt": "cmd",
    "cmd": "cmd",
    "powershell": "powershell",
    "pwsh": "pwsh",
    "task scheduler": "taskschd.msc",
    "system information": "msinfo32",
    "about": "ms-settings:about",
    "network connections": "ncpa.cpl",
    "sound settings": "mmsys.cpl",
    "mouse settings": "main.cpl",
    # ── Browsers ──
    "chrome": "chrome",
    "google chrome": "chrome",
    "browser": "chrome",
    "web browser": "chrome",
    "firefox": "firefox",
    "mozilla": "firefox",
    "edge": "msedge",
    "microsoft edge": "msedge",
    "brave": "brave",
    "brave browser": "brave",
    "opera": "opera",
    "safari": "safari",
    # ── Dev ──
    "vscode": "code",
    "vs code": "code",
    "visual studio code": "code",
    "code": "code",
    "code editor": "code",
    "visual studio": "devenv",
    "pycharm": "pycharm",
    "intellij": "idea",
    "webstorm": "webstorm",
    "sublime text": "sublime_text",
    "sublime": "sublime_text",
    "atom": "atom",
    "notepad plus plus": "notepad++",
    "notepad++": "notepad++",
    "git bash": "git-bash",
    "docker": "docker",
    "tableau": "tableau",
    "postman": "postman",
    "insomnia": "insomnia",
    # ── Media ──
    "spotify": "spotify",
    "music": "spotify",
    "audio player": "spotify",
    "discord": "discord",
    "whatsapp": "whatsapp",
    "telegram": "telegram",
    "signal": "signal",
    "slack": "slack",
    "teams": "teams",
    "microsoft teams": "teams",
    "zoom": "zoom",
    "skype": "skype",
    "vlc": "vlc",
    "media player": "vlc",
    "video player": "vlc",
    "mpv": "mpv",
    "netflix": "netflix",
    "prime video": "primevideo",
    "hulu": "hulu",
    "youtube": "youtube",
    "obs": "obs",
    "obs studio": "obs",
    "audacity": "audacity",
    "foobar2000": "foobar2000",
    # ── Productivity ──
    "office": "winword",
    "word": "winword",
    "excel": "excel",
    "powerpoint": "powerpoint",
    "outlook": "outlook",
    "onenote": "onenote",
    "access": "msaccess",
    "publisher": "mspub",
    "adobe": "acrobat",
    "acrobat": "acrobat",
    "pdf reader": "acrobat",
    "adobe reader": "acrobat",
    "foxit": "foxit",
    "obsidian": "obsidian",
    "notion": "notion",
    "evernote": "evernote",
    "trello": "trello",
    "asana": "asana",
    "jira": "jira",
    "confluence": "confluence",
    "bitbucket": "bitbucket",
    "github desktop": "github",
    "gitkraken": "gitkraken",
    "figma": "figma",
    "blender": "blender",
    "photoshop": "photoshop",
    "gimp": "gimp",
    "unity": "unity",
    "unreal": "unrealeditor",
    # ── Gaming ──
    "steam": "steam",
    "epic games": "com.epicgames.launcher",
    "epic": "com.epicgames.launcher",
    "battle net": "battle.net",
    "blizzard": "battle.net",
    "origin": "origin",
    "ubisoft connect": "ubisoftconnect",
    "minecraft": "minecraft",
    "rob1ox": "roblox",
    "fortnite": "fortnite",
}


def _canonical_app(name: str) -> str:
    name = name.strip().lower()
    if name in APP_ALIASES:
        return APP_ALIASES[name]
    # Strip trailing qualifiers like "with my account", "for me", "please"
    # and retry. ponytail: cheap heuristic — if it's not an alias, strip
    # trailing prepositional phrases to find the real app name.
    for sep in (" with ", " for ", " in ", " please", " thanks"):
        idx = name.rfind(sep)
        if idx > 0:
            candidate = name[:idx]
            if candidate in APP_ALIASES:
                return APP_ALIASES[candidate]
    return name


# ── Handler factories ──────────────────────────────────────────────────

def _open_app(m: re.Match) -> Intent:
    return Intent(action="open_app", target=_canonical_app(m.group("app")))


def _close_app(m: re.Match) -> Intent:
    return Intent(action="close_app", target=_canonical_app(m.group("app")))


def _get_time(_m: re.Match) -> Intent:
    return Intent(action="get_time", target="")


def _play_youtube(m: re.Match) -> Intent:
    return Intent(action="play_youtube", target=m.group("query").strip())


def _search_youtube(m: re.Match) -> Intent:
    return Intent(action="search_youtube", target=m.group("query").strip())


def _search_google(m: re.Match) -> Intent:
    return Intent(action="search_google", target=m.group("query").strip())


def _open_url(m: re.Match) -> Intent:
    return Intent(action="open_url", target=m.group("url").strip())


def _set_volume(m: re.Match) -> Intent:
    level = m.group("level")
    return Intent(action="set_volume", target="", args={"level": int(level)})


def _volume_up(m: re.Match) -> Intent:
    return Intent(action="volume_up", target="")


def _volume_down(m: re.Match) -> Intent:
    return Intent(action="volume_down", target="")


def _mute(m: re.Match) -> Intent:
    return Intent(action="mute", target="")


def _unmute(m: re.Match) -> Intent:
    return Intent(action="unmute", target="")


def _set_brightness(m: re.Match) -> Intent:
    level = m.group("level")
    return Intent(action="set_brightness", target="", args={"level": int(level)})


def _brightness_up(m: re.Match) -> Intent:
    return Intent(action="brightness_up", target="")


def _brightness_down(m: re.Match) -> Intent:
    return Intent(action="brightness_down", target="")


def _get_weather(m: re.Match) -> Intent:
    location = m.group("location") or ""
    return Intent(action="get_weather", target=location.strip())


def _get_weather_forecast(m: re.Match) -> Intent:
    location = m.group("location") or ""
    return Intent(action="get_weather_forecast", target=location.strip())


def _get_news(m: re.Match) -> Intent:
    topic = m.group("topic") or ""
    return Intent(action="get_news", target=topic.strip())


def _get_battery(_m: re.Match) -> Intent:
    return Intent(action="get_battery", target="")


def _get_system_status(_m: re.Match) -> Intent:
    return Intent(action="get_system_status", target="")


def _shutdown(_m: re.Match) -> Intent:
    return Intent(action="shutdown_pc", target="")


def _restart(_m: re.Match) -> Intent:
    return Intent(action="restart_pc", target="")


def _sleep(_m: re.Match) -> Intent:
    return Intent(action="sleep_pc", target="")


def _lock(_m: re.Match) -> Intent:
    return Intent(action="lock_screen", target="")


def _screenshot(m: re.Match) -> Intent:
    region = m.group("region") or ""
    return Intent(action="ocr_screen" if region == "screen" else "screenshot", target="")


def _take_note(m: re.Match) -> Intent:
    return Intent(action="take_note", target=m.group("note").strip())


def _read_notes(_m: re.Match) -> Intent:
    return Intent(action="read_notes", target="")


def _set_reminder(m: re.Match) -> Intent:
    text = ""
    try:
        text = m.group("text") or ""
    except IndexError:
        pass
    if not text:
        try:
            text = m.group("what") or ""
        except IndexError:
            pass
    return Intent(action="set_reminder", target=text.strip())


def _list_reminders(_m: re.Match) -> Intent:
    return Intent(action="list_reminders", target="")


def _translate(m: re.Match) -> Intent:
    text = m.group("text") or ""
    lang = m.group("lang") or ""
    return Intent(action="translate", target=text.strip(), args={"lang": lang.strip()})


def _summarize(m: re.Match) -> Intent:
    text = m.group("text") or ""
    return Intent(action="summarize_url" if text.startswith("http") else "summarize_pdf", target=text.strip())


def _calculate(m: re.Match) -> Intent:
    expr = m.group("expr") or ""
    return Intent(action="calculate", target=expr.strip())


def _define(m: re.Match) -> Intent:
    word = m.group("word") or ""
    return Intent(action="define", target=word.strip())


def _open_folder(m: re.Match) -> Intent:
    path = m.group("path") or ""
    return Intent(action="open_folder", target=path.strip())


def _find_file(m: re.Match) -> Intent:
    name = m.group("name") or ""
    return Intent(action="find_file", target=name.strip())


# ── Phase D2: Prefix trie for sub-millisecond matching ─────────────────
# Patterns are grouped by their first token so match() only checks a
# handful of candidates instead of iterating all 40+ patterns linearly.
# Catch-all patterns (no specific first word) go under None.

def _first_token(text: str) -> str | None:
    s = text.strip()
    idx = s.find(" ")
    return s[:idx] if idx > 0 else s


RuleEntry = tuple[re.Pattern, Callable[[re.Match], Intent]]

# Longest-first so multi-word aliases ("visual studio code") win over any
# shorter alias that prefixes them.
_APP_ALIAS_ALT = "|".join(
    re.escape(k) for k in sorted(APP_ALIASES, key=len, reverse=True)
)


def _split_top_level(body: str) -> list[str]:
    """Split on '|' at paren depth 0 only."""
    parts, depth, cur = [], 0, []
    for ch in body:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "|" and depth == 0:
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    parts.append("".join(cur))
    return parts


def _match_group(src: str, start: int) -> tuple[str, int] | None:
    """Given src[start] == '(', return (inner_body, index_after_close)."""
    if start >= len(src) or src[start] != "(":
        return None
    depth, i = 0, start
    while i < len(src):
        if src[i] == "(":
            depth += 1
        elif src[i] == ")":
            depth -= 1
            if depth == 0:
                inner = src[start + 1 : i]
                # Drop a leading group qualifier: (?: , (?P<name> , (?= etc.
                inner = re.sub(r"^\?(?::|P<\w+>)", "", inner)
                return inner, i + 1
        i += 1
    return None


# A partially-built first token: (text_so_far, ended_at_a_word_boundary).
# The flag matters because `(?:take\s+a\s+)?screenshot` must yield {"take",
# "screenshot"} — NOT "takescreenshot". Once a branch hits whitespace its token
# is complete and later literals belong to the second word.
_State = tuple[str, bool]


def _concat(a: _State, b: _State) -> _State:
    text, done = a
    return (text, True) if done else (text + b[0], b[1])


def _expand_states(src: str) -> set[_State] | None:
    """Every literal first-token a regex body can begin with.

    Must understand nesting: `what(?:'s| is)?\\s+...` begins "what" OR
    "what's". A naive scan stopping at the first ')' mangles that into
    `what(?:'s`, fails to parse, and demotes the rule to the catch-all bucket —
    silently losing its priority over greedier rules.

    Returns None when the first token cannot be determined, meaning the rule
    must stay a catch-all.
    """
    out: set[_State] = {("", False)}
    i = 0
    while i < len(src):
        ch = src[i]

        if ch.isalnum() or ch in "'_":
            # A trailing '?' makes just this character optional, as in
            # what'?s — which must bucket under both "whats" and "what's".
            if i + 1 < len(src) and src[i + 1] == "?":
                out = {_concat(s, (ch, False)) for s in out} | out
                i += 2
            else:
                out = {_concat(s, (ch, False)) for s in out}
                i += 1
            continue

        if ch == "(":
            grp = _match_group(src, i)
            if grp is None:
                return None
            inner, after = grp
            optional = after < len(src) and src[after] == "?"
            branches: set[_State] = set()
            for alt in _split_top_level(inner):
                sub = _expand_states(alt)
                if sub is None:
                    return None
                branches |= sub
            if optional:
                branches.add(("", False))
                after += 1
            out = {_concat(s, b) for s in out for b in branches}
            i = after
            continue

        # Whitespace closes the first token; everything after belongs to word 2.
        if src.startswith("\\s", i) or ch == " ":
            out = {(t, True) for t, _ in out}
            i += 2 if ch == "\\" else 1
            continue

        if ch == "$":
            break

        # Any other metacharacter: the token is only known if fully built.
        if all(done and text for text, done in out):
            break
        return None

    return out


def _clean(states: set[_State]) -> set[str] | None:
    tokens = {t for t, _ in states if t}
    return tokens or None


def _leading_tokens(src: str) -> list[str] | None:
    """First literal token(s) a pattern can start with, or None for a catch-all.

    A pattern like ^(?:calculate|what\\s+is|what's)\\s+... can be entered by
    three different words. Registering only the first left the other two
    reachable solely via a full linear scan, which handed every greedy pattern
    a shot at every input.
    """
    if not src.startswith("^"):
        return None
    states = _expand_states(src[1:])
    if states is None:
        return None
    expanded = _clean(states)
    return sorted(expanded) if expanded else None


def _token_variants(tok: str) -> set[str]:
    """Both spellings of a token that contains an apostrophe.

    normalize_for_rules keeps apostrophes but normalize strips them, and rules
    are matched against user speech either way, so "what's" must be findable
    as both "what's" and "whats".

    Currently REDUNDANT: now that the rules spell the apostrophe as optional
    (what'?s) and _expand_states understands a '?' after a single character,
    _leading_tokens already emits both spellings — the trie is byte-identical
    without this function. Kept as a safety net for any future rule that
    hard-codes an apostrophe, pending a decision on removing it.

    Note it only ever fixed *bucketing*, never matching: a pattern that
    hard-codes "what's" stays unmatchable by "whats" no matter which bucket
    it sits in. That gap is what the apostrophe regression was.
    """
    variants = {tok}
    if "'" in tok:
        variants.add(tok.replace("'", ""))
    return variants


def _build_trie(rules: list[RuleEntry]) -> dict[str | None, list[RuleEntry]]:
    trie: dict[str | None, list[RuleEntry]] = {}
    for pattern, handler in rules:
        tokens = _leading_tokens(pattern.pattern)
        if tokens is None:
            trie.setdefault(None, []).append((pattern, handler))
            continue
        # Register under every entry token, and under each apostrophe-less
        # spelling, so the fast path alone is sufficient.
        for tok in {v for t in tokens for v in _token_variants(t)}:
            trie.setdefault(tok, []).append((pattern, handler))
    return trie


# ── Phase D1: 40+ Patterns ─────────────────────────────────────────────
RULES: list[RuleEntry] = [
    # ── YouTube (most-specific phrasings first) ──
    (re.compile(r"^play\s+(?P<query>.+?)\s+on\s+youtube$"), _play_youtube),
    (re.compile(r"^search\s+(?:for\s+)?(?P<query>.+?)\s+on\s+youtube$"), _search_youtube),
    (re.compile(r"^show\s+(?:me\s+)?(?P<query>.+?)\s+on\s+youtube$"), _search_youtube),
    (re.compile(r"^search\s+(?:for\s+)?(?P<query>.+?)\s+on\s+google$"), _search_google),
    (re.compile(r"^youtube\s+(?P<query>.+)$"), _search_youtube),
    (re.compile(r"^google\s+(?P<query>.+)$"), _search_google),
    (re.compile(r"^search\s+(?:for\s+)?(?P<query>.+)$"), _search_google),
    (re.compile(r"^play\s+(?P<query>.+)$"), _play_youtube),

    # ── URL (before app management so "open github.com" doesn't match open_app) ──
    (re.compile(r"^(?:open|go\s+to)\s+(?P<url>(?:https?://)?(?:localhost|[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)+)(?::\d{1,5})?(?:/[^\s]*)?)$"), _open_url),
    (re.compile(r"^(?P<url>(?:https?://)?(?:localhost|[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)+)(?::\d{1,5})?(?:/[^\s]*)?)$"), _open_url),

    # ── App management ──
    # Negative lookahead excludes "with"/"for"/"in" qualifiers so those
    # commands fall through to the LLM agent (which handles profiles).
    # Target must be a known alias or a single bare token. Previously any
    # trailing text matched, so "start working on the report" became
    # open_app("working on the report"). "start" is dropped from the verb list
    # entirely — it is the weakest of the three signals and overwhelmingly
    # conversational ("start working on", "start the meeting"), while
    # open/launch are unambiguously imperative.
    (re.compile(
        rf"^(?:open|launch)\s+(?P<app>(?!.*\s+(?:with|for|in)\s)"
        rf"(?:{_APP_ALIAS_ALT}|[\w.+-]+))$"), _open_app),
    (re.compile(r"^(?:close|quit|exit|kill)\s+(?P<app>(?!.*\s+(?:with|for|in)\s).+?)$"), _close_app),

    # ── Volume ──
    (re.compile(r"^(?:set|change)\s+volume\s+to\s+(?P<level>\d{1,3})\s*(?:percent)?$"), _set_volume),
    (re.compile(r"^volume\s+(?P<level>\d{1,3})\s*(?:percent)?$"), _set_volume),
    (re.compile(r"^volume\s+up$"), _volume_up),
    (re.compile(r"^volume\s+down$"), _volume_down),
    (re.compile(r"^(?:turn\s+up|increase)\s+(?:the\s+)?volume$"), _volume_up),
    (re.compile(r"^(?:turn\s+down|decrease)\s+(?:the\s+)?volume$"), _volume_down),
    (re.compile(r"^(?:mute|silence)\s*(?:audio|sound|volume)?$"), _mute),
    (re.compile(r"^(?:unmute|unsilence)\s*(?:audio|sound|volume)?$"), _unmute),

    # ── Brightness ──
    (re.compile(r"^(?:set|change)\s+brightness\s+to\s+(?P<level>\d{1,3})\s*(?:percent)?$"), _set_brightness),
    (re.compile(r"^brightness\s+(?P<level>\d{1,3})\s*(?:percent)?$"), _set_brightness),
    (re.compile(r"^brightness\s+up$"), _brightness_up),
    (re.compile(r"^brightness\s+down$"), _brightness_down),
    (re.compile(r"^(?:turn\s+up|increase)\s+(?:the\s+)?brightness$"), _brightness_up),
    (re.compile(r"^(?:turn\s+down|decrease)\s+(?:the\s+)?brightness$"), _brightness_down),

    # ── Weather ──
    (re.compile(r"^(?:what(?:'?s| is)?\s+(?:the\s+)?weather(?:\s+(?:in|for|at)\s+(?P<location>.+?))?|weather\s+(?:in|for|at)\s+(?P<location2>.+?))$"), _get_weather),
    (re.compile(r"^(?:what(?:'?s| is)?\s+(?:the\s+)?forecast(?:\s+(?:in|for|at)\s+(?P<location>.+?))?|forecast\s+(?:in|for|at)\s+(?P<location2>.+?))$"), _get_weather_forecast),

    # ── News ──
    (re.compile(r"^(?:what(?:'?s| is)?\s+(?:the\s+)?(?:news|headlines)(?:\s+(?:about|on|for)\s+(?P<topic>.+?))?|(?:get|show)\s+(?:me\s+)?(?:the\s+)?(?:news|headlines)(?:\s+(?:about|on|for)\s+(?P<topic2>.+?))?|(?:news|headlines)\s+(?:about|on|for)\s+(?P<topic3>.+?))$"), _get_news),

    # ── System power ──
    (re.compile(r"^(?:shutdown|shut\s+down|power\s+off|turn\s+off)\s*(?:the\s+)?(?:computer|pc)?$"), _shutdown),
    (re.compile(r"^(?:restart|reboot)\s*(?:the\s+)?(?:computer|pc)?$"), _restart),
    (re.compile(r"^(?:sleep|hibernate)\s*(?:the\s+)?(?:computer|pc)?$"), _sleep),
    (re.compile(r"^(?:lock)\s*(?:the\s+)?(?:computer|pc|screen)?$"), _lock),
    (re.compile(r"^(?:sign\s+out|log\s+out)\s*(?:of\s+)?(?:computer|pc)?$"), _lock),

    # ── Battery / System info ──
    (re.compile(r"^(?:what(?:'?s| is)?\s+my\s+battery(?:\s+(?:level|status|percentage))?|battery\s+(?:level|status|percentage|life)|how\s+much\s+battery\s+(?:do\s+i\s+have|is\s+left)|check\s+battery)$"), _get_battery),
    (re.compile(r"^(?:system\s+status|system\s+info|pc\s+status|computer\s+status)$"), _get_system_status),

    # ── Screenshot ──
    (re.compile(r"^(?:take\s+a\s+)?screenshot(?:\s+of\s+(?P<region>screen|window|area))?$"), _screenshot),

    # ── Notes ──
    (re.compile(r"^(?:take\s+(?:a\s+)?)?note\s+(?P<note>.+)$"), _take_note),
    (re.compile(r"^(?:take\s+(?:a\s+)?)?note$"), _read_notes),
    (re.compile(r"^(?:read|show|get)\s+(?:my\s+)?notes$"), _read_notes),
    (re.compile(r"^open\s+(?:my\s+)?notes$"), _read_notes),

    # ── Reminders ──
    (re.compile(r"^(?:set|create|add)\s+(?:a\s+)?reminder\s+(?:to\s+)?(?P<text>.+?)(?:\s+in\s+(?P<time>.+?))?$"), _set_reminder),
    # Requires the "to", or a trailing "in <duration>". "remind me to call mom"
    # is a reminder; "remind me why we chose Postgres" is a question and must
    # reach the LLM.
    (re.compile(r"^remind\s+me\s+to\s+(?P<what>.+?)(?:\s+in\s+(?P<time>.+?))?$"), _set_reminder),
    (re.compile(r"^remind\s+me\s+(?P<what>.+?)\s+in\s+(?P<time>\d+\s*\w+.*?)$"), _set_reminder),
    (re.compile(r"^(?:list|show|get)\s+(?:my\s+)?reminders$"), _list_reminders),

    # ── Translate ──
    (re.compile(r"^translate\s+(?P<text>.+?)(?:\s+(?:to|into|in)\s+(?P<lang>[a-z]+(?:\s*[a-z]+)*))?$"), _translate),

    # ── Summarize ──
    # Only fires for a URL or a file with an extension. "summarize the plot of
    # hamlet" is a question for the LLM, not a document to fetch.
    (re.compile(
        r"^summarize\s+(?P<text>"
        r"(?:https?://\S+)"                        # explicit URL
        r"|(?:[\w-]+\.)+[a-z]{2,}(?:[:/]\S*)?"     # bare domain, optional path
        r"|\S*[/\\]\S*\.\w{1,5}"                   # path with extension
        r"|\S+\.(?:pdf|docx?|txt|md|pptx?|xlsx?|csv|html?|epub)"
        r")$"), _summarize),

    # ── Calculator ──
    # "calculate X" keeps a permissive target: the explicit verb is an
    # unambiguous signal of intent. "what is X" / "what's X" must NOT be —
    # it used to swallow every general-knowledge question ("what is the
    # capital of France" -> calculate). Those forms now require the target to
    # look arithmetic: digits with operators/parens, or a spelled-out
    # operation.
    (re.compile(r"^calculate\s+(?P<expr>.+)$"), _calculate),
    (re.compile(
        r"^what(?:'?s|\s+is)\s+"
        r"(?P<expr>"
        r"[\d(].*[\d)%]"            # starts and ends numeric/paren
        r"|\d+(?:\.\d+)?\s*(?:plus|minus|times|divided\s+by|mod(?:ulo)?)\s+.*"
        r"|\d+(?:\.\d+)?\s*(?:percent|%)\s+of\s+.*"
        r")$"), _calculate),
    (re.compile(r"^(?P<expr>\d+\s*[\+\-\*\/\%]\s*\d+.*)$"), _calculate),

    # ── Dictionary ──
    (re.compile(r"^(?:define|what\s+(?:does|is)\s+the\s+meaning\s+of)\s+(?P<word>\w+)$"), _define),

    # ── Folder / File ops ──
    (re.compile(r"^(?:open|navigate\s+to)\s+(?:the\s+)?(?:folder|directory)\s+(?P<path>.+)$"), _open_folder),
    (re.compile(r"^find\s+(?:the\s+)?(?:file|folder)\s+(?P<name>.+)$"), _find_file),

    # ── Time ──
    (re.compile(r"^(?:what(?:\s+is)?\s+the\s+time|what\s+time\s+is\s+it|current\s+time|tell\s+me\s+the\s+time|what'?s\s+the\s+time|time\s+now|what\s+time\s+do\s+we\s+have)$"), _get_time),
]

TRIE = _build_trie(RULES)


def match(normalized_text: str) -> Intent | None:
    """Match against normalized (lowercased, depunctuated) text.
    
    Uses a prefix trie for sub-millisecond matching — only patterns sharing
    the first token of the input are checked, plus catch-all (None token) rules.
    Falls back to full linear scan only if the trie misses.
    """
    first = _first_token(normalized_text)
    candidates = TRIE.get(first, [])
    if first is not None:
        candidates = candidates + TRIE.get(None, [])

    for pattern, factory in candidates:
        m = pattern.match(normalized_text)
        if m:
            return factory(m)

    # No fallback scan. It used to re-check every rule when the trie missed,
    # which meant a greedy pattern got a shot at every input regardless of its
    # first token — the trie was a fast path, never a filter. _build_trie now
    # registers a pattern under every leading alternative, so the trie lookup
    # plus the None bucket is complete.
    return None
