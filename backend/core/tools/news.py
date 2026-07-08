"""News + trending + daily briefing (Phase 11d).

- News via RSS (BBC, Hacker News, TechCrunch, Al Jazeera, NYT).
- Trending via Reddit r/popular JSON (no API key, just a user-agent).
- daily_briefing chains time + weather + top news into one spoken summary.
"""
import feedparser
import httpx

from backend.core.tools.registry import CapabilityTier, tool

NEWS_FEEDS: dict[str, str] = {
    "world": "http://feeds.bbci.co.uk/news/rss.xml",
    "tech": "https://hnrss.org/frontpage",
    "hackernews": "https://hnrss.org/frontpage",
    "techcrunch": "https://techcrunch.com/feed/",
    "business": "https://feeds.bbci.co.uk/news/business/rss.xml",
    "india": "https://www.thehindu.com/news/national/feeder/default.rss",
    "science": "https://www.sciencedaily.com/rss/all.xml",
    "sports": "https://feeds.bbci.co.uk/sport/rss.xml",
}

REDDIT_URL = "https://www.reddit.com/r/popular.json"


@tool(tier=CapabilityTier.READONLY)  # tier: RSS fetch, no side effects
def get_news(category: str = "world", limit: int = 5) -> dict:
    """Read top headlines from an RSS feed. Categories: world, tech,
    techcrunch, business, india, science, sports. Default is "world" (BBC)."""
    cat = category.strip().lower()
    url = NEWS_FEEDS.get(cat)
    if url is None:
        return {
            "status": "blocked",
            "reason": f"unknown category {category!r} (try one of: {', '.join(NEWS_FEEDS)})",
        }

    try:
        feed = feedparser.parse(url)
    except Exception as e:
        return {"status": "error", "reason": f"feed parse failed: {e}"}

    entries = feed.entries[: max(1, min(int(limit), 10))]
    items = [{"title": e.title, "link": getattr(e, "link", "")} for e in entries if hasattr(e, "title")]
    if not items:
        return {"status": "blocked", "reason": f"no headlines in {cat}"}

    summary = " — ".join(it["title"] for it in items[:3])
    return {
        "status": "success",
        "message": f"Top {cat} headlines: {summary}",
        "args": {"category": cat, "items": items},
    }


@tool(tier=CapabilityTier.READONLY)  # tier: Reddit HTTP GET, no side effects
def get_trending(limit: int = 5) -> dict:
    """Read what is trending right now on Reddit's r/popular. Useful for
    "what's everyone talking about" type queries."""
    try:
        with httpx.Client(timeout=10.0) as c:
            r = c.get(REDDIT_URL, headers={"User-Agent": "SG_CUBE/1.0 (voice assistant)"})
    except Exception as e:
        return {"status": "error", "reason": f"reddit error: {e}"}

    if r.status_code != 200:
        return {"status": "blocked", "reason": f"reddit HTTP {r.status_code}"}

    data = r.json().get("data") or {}
    posts = data.get("children") or []
    items = []
    for p in posts[: max(1, min(int(limit), 10))]:
        d = p.get("data") or {}
        items.append(
            {
                "title": d.get("title"),
                "subreddit": d.get("subreddit"),
                "score": d.get("score"),
            }
        )
    if not items:
        return {"status": "blocked", "reason": "no trending posts"}

    summary = " — ".join(f"{it['title']} (r/{it['subreddit']})" for it in items[:3])
    return {
        "status": "success",
        "message": f"Trending on Reddit: {summary}",
        "args": {"items": items},
    }


@tool(tier=CapabilityTier.READONLY)  # tier: composes time+weather+news read-only sources, no side effects
def daily_briefing() -> dict:
    """Read out a morning briefing: current time + local weather + top three
    world headlines + (if any) active reminders. Use for "give me my daily
    briefing" or "what's the briefing"."""
    # Lazy imports to avoid circular dependency with builtins.
    from backend.core.tools.news import get_news
    from backend.core.tools.reminders import list_reminders
    from backend.core.tools.weather import get_weather
    from backend.core.tools.system_info import get_battery  # noqa: F401 — placeholder
    from backend.core.safe_executor.command_whitelist import handle_get_time
    from backend.core.orchestrator.llm_layer import Intent

    sections: list[str] = []

    t = handle_get_time(Intent(action="get_time", target=""))
    if t.get("status") == "success":
        sections.append(f"The time is {t.get('message')}.")

    wx = get_weather("")
    if wx.get("status") == "success":
        sections.append(wx.get("message", ""))

    nx = get_news("world", limit=3)
    if nx.get("status") == "success":
        items = (nx.get("args") or {}).get("items") or []
        if items:
            heads = " — ".join(it["title"] for it in items[:3])
            sections.append(f"Top headlines: {heads}.")

    rem = list_reminders()
    if rem.get("status") == "success":
        items = (rem.get("args") or {}).get("reminders") or []
        if items:
            sections.append(f"You have {len(items)} active reminder(s).")

    if not sections:
        return {"status": "blocked", "reason": "couldn't fetch any briefing data"}

    summary = " ".join(sections)
    return {"status": "success", "message": summary, "args": {"sections": sections}}
