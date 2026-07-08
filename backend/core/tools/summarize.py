"""Summarize tools (Phase 11e) — PDFs, web pages, and source files.

All three flow the same way: extract text → LLM (gemma4) → short summary.
"""
from pathlib import Path

import httpx
from bs4 import BeautifulSoup
from pypdf import PdfReader

from backend.core.tools.files import SEARCH_ROOTS
from backend.core.tools.llm_helper import llm_generate
from backend.core.tools.registry import CapabilityTier, ToolResult, tool

MAX_CHARS = 6000  # cap text fed to the LLM — keeps a single call snappy

SUMMARIZE_SYSTEM = (
    "You are a concise summarizer for a voice assistant. Return ONE paragraph, "
    "5 sentences max, in plain prose. No bullet points, no markdown, no preface "
    "like 'This document is about'. Just the summary itself."
)

EXPLAIN_SYSTEM = (
    "You are a senior engineer explaining code to a colleague over voice. "
    "Return 3 short sentences in plain prose: (1) what the file does, (2) its "
    "main pieces, (3) anything subtle worth noting. No code blocks, no markdown."
)


def _resolve_file(name: str, suffix: str | None = None) -> Path | None:
    """Resolve `name` to a real file path.

    1. If `name` is already a full path that exists, use it.
    2. Otherwise search `SEARCH_ROOTS` (Desktop/Downloads/Documents/...) for the
       first file whose name contains `name` (optionally filtered by suffix).
    """
    p = Path(name).expanduser()
    if p.exists() and p.is_file():
        return p

    q = name.strip().lower()
    if not q:
        return None
    for root in SEARCH_ROOTS:
        if not root.exists():
            continue
        try:
            for candidate in root.rglob("*"):
                if not candidate.is_file():
                    continue
                if suffix and candidate.suffix.lower() != suffix:
                    continue
                if q in candidate.name.lower():
                    return candidate
        except (PermissionError, OSError):
            continue
    return None


@tool(tier=CapabilityTier.READONLY)  # tier: reads PDF + summarizes via LLM, no side effects
def summarize_pdf(file: str) -> ToolResult:
    """Summarize a PDF file. `file` is a full path or a substring of a PDF
    name in Desktop/Downloads/Documents/Pictures/Videos/Music. Reads the text
    with pypdf and asks gemma4 for a one-paragraph summary."""
    path = _resolve_file(file, suffix=".pdf")
    if not path:
        return ToolResult.blocked(f"no PDF matching {file!r}")

    try:
        reader = PdfReader(str(path))
    except Exception as e:
        return ToolResult.error(f"could not read PDF: {e}")

    parts: list[str] = []
    total = 0
    pages_read = 0
    for page in reader.pages:
        try:
            txt = page.extract_text() or ""
        except Exception:
            continue
        pages_read += 1
        if not txt:
            continue
        parts.append(txt)
        total += len(txt)
        if total >= MAX_CHARS:
            break

    text = ("\n".join(parts))[:MAX_CHARS].strip()
    if not text:
        return ToolResult.blocked("PDF contains no extractable text")

    summary = llm_generate(
        f"Summarize this document:\n\n{text}",
        system=SUMMARIZE_SYSTEM,
    )
    if not summary:
        return ToolResult.error("summarizer model returned nothing")

    # Calculate confidence
    read_ratio = pages_read / len(reader.pages) if reader.pages else 0
    confidence = 70.0 + (read_ratio * 30.0) # Base 70, up to 100
    
    reason = [
        f"Read {pages_read} of {len(reader.pages)} pages",
        f"Extracted {len(text)} characters",
        "LLM summary generation successful"
    ]
    if read_ratio < 1.0:
        reason.insert(0, "Partial document read due to size limit")

    return ToolResult.success(
        message=summary,
        data={"file": str(path), "pages": len(reader.pages), "chars_used": len(text)},
        confidence=confidence,
        confidence_reason=reason
    )


@tool(tier=CapabilityTier.READONLY)  # tier: HTTP GET + summarize, no side effects
def summarize_url(url: str) -> ToolResult:
    """Summarize a web page. Fetches `url`, strips HTML to text with
    BeautifulSoup, and asks gemma4 for a one-paragraph summary."""
    if not url.strip():
        return ToolResult.blocked("empty URL")
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    try:
        with httpx.Client(timeout=15.0, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0 (SG_CUBE)"}) as c:
            r = c.get(url)
    except Exception as e:
        return ToolResult.error(f"fetch failed: {e}")

    if r.status_code != 200:
        return ToolResult.blocked(f"HTTP {r.status_code}")

    soup = BeautifulSoup(r.text, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "aside", "noscript"]):
        tag.decompose()

    title = (soup.title.string.strip() if soup.title and soup.title.string else "").strip()
    text = " ".join(soup.get_text(" ").split())[:MAX_CHARS]
    if len(text) < 200:
        return ToolResult.blocked("page had too little text to summarize")

    summary = llm_generate(
        f"Summarize this web page (title: {title!r}):\n\n{text}",
        system=SUMMARIZE_SYSTEM,
    )
    if not summary:
        return ToolResult.error("summarizer model returned nothing")

    return ToolResult.success(
        message=summary,
        data={"url": url, "title": title, "chars_used": len(text)},
        confidence=95.0,
        confidence_reason=[
            "Web content successfully fetched",
            "HTML boilerplate stripped",
            "Sufficient text for analysis"
        ]
    )


@tool(tier=CapabilityTier.READONLY)  # tier: reads code + LLM explain, no side effects
def explain_code(file: str) -> ToolResult:
    """Explain what a source code file does in three short sentences.
    `file` is a full path or a substring of a file name in your common
    user folders. Works for any text-based file (.py, .js, .ts, .go, etc.)."""
    path = _resolve_file(file)
    if not path:
        return ToolResult.blocked(f"no file matching {file!r}")

    try:
        text = path.read_text(encoding="utf-8", errors="ignore")[:MAX_CHARS]
    except Exception as e:
        return ToolResult.error(f"could not read file: {e}")

    if not text.strip():
        return ToolResult.blocked("file is empty")

    summary = llm_generate(
        f"Explain this {path.suffix} file named {path.name}:\n\n{text}",
        system=EXPLAIN_SYSTEM,
    )
    if not summary:
        return ToolResult.error("explain model returned nothing")

    return ToolResult.success(
        message=summary,
        data={"file": str(path), "chars_used": len(text)},
        confidence=92.0,
        confidence_reason=[
            f"Successfully read {path.suffix} file",
            f"Analyzed {len(text)} characters",
            "LLM explanation generated"
        ]
    )
