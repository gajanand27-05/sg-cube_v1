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
    return APP_ALIASES.get(name, name)


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


def _build_trie(rules: list[RuleEntry]) -> dict[str | None, list[RuleEntry]]:
    trie: dict[str | None, list[RuleEntry]] = {}
    for pattern, handler in rules:
        # Extract first literal token from the regex pattern
        src = pattern.pattern
        # Patterns starting with ^(?:word|... or ^word
        m = re.match(r"\^\(?\?:(?P<tok>\w+)|^\^(?P<tok2>\w+)", src)
        if m:
            tok = m.group("tok") or m.group("tok2")
        else:
            tok = None
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
    (re.compile(r"^(?:open|go\s+to)\s+(?P<url>(?:https?://)?[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)+(?::\d{1,5})?(?:/[^\s]*)?)$"), _open_url),
    (re.compile(r"^(?P<url>(?:https?://)?[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)+(?::\d{1,5})?(?:/[^\s]*)?)$"), _open_url),

    # ── App management ──
    (re.compile(r"^(?:open|launch|start)\s+(?P<app>.+?)$"), _open_app),
    (re.compile(r"^(?:close|quit|exit|kill)\s+(?P<app>.+?)$"), _close_app),

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
    (re.compile(r"^(?:what(?:'s| is)?\s+(?:the\s+)?weather(?:\s+(?:in|for|at)\s+(?P<location>.+?))?|weather\s+(?:in|for|at)\s+(?P<location2>.+?))$"), _get_weather),
    (re.compile(r"^(?:what(?:'s| is)?\s+(?:the\s+)?forecast(?:\s+(?:in|for|at)\s+(?P<location>.+?))?|forecast\s+(?:in|for|at)\s+(?P<location2>.+?))$"), _get_weather_forecast),

    # ── News ──
    (re.compile(r"^(?:what(?:'s| is)?\s+(?:the\s+)?(?:news|headlines)(?:\s+(?:about|on|for)\s+(?P<topic>.+?))?|(?:get|show)\s+(?:me\s+)?(?:the\s+)?(?:news|headlines)(?:\s+(?:about|on|for)\s+(?P<topic2>.+?))?|(?:news|headlines)\s+(?:about|on|for)\s+(?P<topic3>.+?))$"), _get_news),

    # ── System power ──
    (re.compile(r"^(?:shutdown|shut\s+down|power\s+off|turn\s+off)\s*(?:the\s+)?(?:computer|pc)?$"), _shutdown),
    (re.compile(r"^(?:restart|reboot)\s*(?:the\s+)?(?:computer|pc)?$"), _restart),
    (re.compile(r"^(?:sleep|hibernate)\s*(?:the\s+)?(?:computer|pc)?$"), _sleep),
    (re.compile(r"^(?:lock)\s*(?:the\s+)?(?:computer|pc|screen)?$"), _lock),
    (re.compile(r"^(?:sign\s+out|log\s+out)\s*(?:of\s+)?(?:computer|pc)?$"), _lock),

    # ── Battery / System info ──
    (re.compile(r"^(?:what(?:'s| is)?\s+my\s+battery(?:\s+(?:level|status|percentage))?|battery\s+(?:level|status|percentage|life)|how\s+much\s+battery\s+(?:do\s+i\s+have|is\s+left)|check\s+battery)$"), _get_battery),
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
    (re.compile(r"^remind\s+me\s+(?:to\s+)?(?P<what>.+?)(?:\s+in\s+(?P<time>.+?))?$"), _set_reminder),
    (re.compile(r"^(?:list|show|get)\s+(?:my\s+)?reminders$"), _list_reminders),

    # ── Translate ──
    (re.compile(r"^translate\s+(?P<text>.+?)(?:\s+(?:to|into|in)\s+(?P<lang>[a-z]+(?:\s*[a-z]+)*))?$"), _translate),

    # ── Summarize ──
    (re.compile(r"^summarize\s+(?P<text>.+)$"), _summarize),

    # ── Calculator ──
    (re.compile(r"^(?:calculate|what\s+is|what's)\s+(?P<expr>.+)$"), _calculate),
    (re.compile(r"^(?P<expr>\d+\s*[\+\-\*\/\%]\s*\d+.*)$"), _calculate),

    # ── Dictionary ──
    (re.compile(r"^(?:define|what\s+(?:does|is)\s+the\s+meaning\s+of)\s+(?P<word>\w+)$"), _define),

    # ── Folder / File ops ──
    (re.compile(r"^(?:open|navigate\s+to)\s+(?:the\s+)?(?:folder|directory)\s+(?P<path>.+)$"), _open_folder),
    (re.compile(r"^find\s+(?:the\s+)?(?:file|folder)\s+(?P<name>.+)$"), _find_file),

    # ── Time ──
    (re.compile(r"^(?:what(?:\s+is)?\s+the\s+time|what\s+time\s+is\s+it|current\s+time|tell\s+me\s+the\s+time|whats\s+the\s+time|time\s+now|what\s+time\s+do\s+we\s+have)$"), _get_time),
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

    # Full fallback scan for edge cases the trie couldn't bucket
    for pattern, factory in RULES:
        m = pattern.match(normalized_text)
        if m:
            return factory(m)

    return None
