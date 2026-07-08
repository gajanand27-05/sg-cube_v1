"""Read-only web page text extractor (Phase T2-3).

Companion to summarize_url: returns the cleaned plain-text body so
the planner/LLM can quote or excerpt content upstream of any
LLM-side summarization. SAFE — read-only, no side effects.
"""
import httpx
from bs4 import BeautifulSoup

from backend.core.tools.registry import CapabilityTier, ToolResult, tool

_MAX_CHARS = 50_000  # keep prompt sizes sane.


@tool(tier=CapabilityTier.READONLY)  # tier: HTTP GET + HTML strip, no side effects
def read_webpage(url: str) -> ToolResult:
    """Fetch `url` and return its plain-text body (HTML stripped via
    BeautifulSoup). For summarization, see `summarize_url`."""
    url = (url or "").strip()
    if not url:
        return ToolResult.blocked("empty URL")
    if not url.startswith(("http://", "https://")):
        url = "http://" + url

    try:
        with httpx.Client(
            timeout=15.0,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (SG_CUBE)"},
        ) as c:
            r = c.get(url)
    except Exception as e:
        return ToolResult.error(f"fetch failed: {e}")

    if r.status_code != 200:
        return ToolResult.blocked(f"HTTP {r.status_code}")

    soup = BeautifulSoup(r.text, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "aside", "noscript"]):
        tag.decompose()

    title = (soup.title.string.strip() if soup.title and soup.title.string else "").strip()
    text = " ".join(soup.get_text(" ").split())[:_MAX_CHARS]
    if not text:
        return ToolResult.blocked("page had no readable text")

    return ToolResult.success(
        message=text,
        data={"url": url, "title": title, "chars": len(text)},
    )
