"""Summarize tools (Phase 11e) — PDFs, web pages, and source files.

All three flow the same way: extract text → LLM (gemma4) → short summary.
"""
from pathlib import Path

import httpx
from bs4 import BeautifulSoup
from pypdf import PdfReader

from backend.core.tools.files import SEARCH_ROOTS
from backend.core.tools.llm_helper import llm_generate
from backend.core.tools.registry import tool

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


@tool
def summarize_pdf(file: str) -> dict:
    """Summarize a PDF file. `file` is a full path or a substring of a PDF
    name in Desktop/Downloads/Documents/Pictures/Videos/Music. Reads the text
    with pypdf and asks gemma4 for a one-paragraph summary."""
    path = _resolve_file(file, suffix=".pdf")
    if not path:
        return {"status": "blocked", "reason": f"no PDF matching {file!r}"}

    try:
        reader = PdfReader(str(path))
    except Exception as e:
        return {"status": "error", "reason": f"could not read PDF: {e}"}

    parts: list[str] = []
    total = 0
    for page in reader.pages:
        try:
            txt = page.extract_text() or ""
        except Exception:
            continue
        if not txt:
            continue
        parts.append(txt)
        total += len(txt)
        if total >= MAX_CHARS:
            break

    text = ("\n".join(parts))[:MAX_CHARS].strip()
    if not text:
        return {"status": "blocked", "reason": "PDF contains no extractable text"}

    summary = llm_generate(
        f"Summarize this document:\n\n{text}",
        system=SUMMARIZE_SYSTEM,
    )
    if not summary:
        return {"status": "error", "reason": "summarizer model returned nothing"}

    return {
        "status": "success",
        "message": summary,
        "args": {"file": str(path), "pages": len(reader.pages), "chars_used": len(text)},
    }


@tool
def summarize_url(url: str) -> dict:
    """Summarize a web page. Fetches `url`, strips HTML to text with
    BeautifulSoup, and asks gemma4 for a one-paragraph summary."""
    if not url.strip():
        return {"status": "blocked", "reason": "empty URL"}
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    try:
        with httpx.Client(timeout=15.0, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0 (SG_CUBE)"}) as c:
            r = c.get(url)
    except Exception as e:
        return {"status": "error", "reason": f"fetch failed: {e}"}

    if r.status_code != 200:
        return {"status": "blocked", "reason": f"HTTP {r.status_code}"}

    soup = BeautifulSoup(r.text, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "aside", "noscript"]):
        tag.decompose()

    title = (soup.title.string.strip() if soup.title and soup.title.string else "").strip()
    text = " ".join(soup.get_text(" ").split())[:MAX_CHARS]
    if len(text) < 200:
        return {"status": "blocked", "reason": "page had too little text to summarize"}

    summary = llm_generate(
        f"Summarize this web page (title: {title!r}):\n\n{text}",
        system=SUMMARIZE_SYSTEM,
    )
    if not summary:
        return {"status": "error", "reason": "summarizer model returned nothing"}

    return {
        "status": "success",
        "message": summary,
        "args": {"url": url, "title": title, "chars_used": len(text)},
    }


@tool
def explain_code(file: str) -> dict:
    """Explain what a source code file does in three short sentences.
    `file` is a full path or a substring of a file name in your common
    user folders. Works for any text-based file (.py, .js, .ts, .go, etc.)."""
    path = _resolve_file(file)
    if not path:
        return {"status": "blocked", "reason": f"no file matching {file!r}"}

    try:
        text = path.read_text(encoding="utf-8", errors="ignore")[:MAX_CHARS]
    except Exception as e:
        return {"status": "error", "reason": f"could not read file: {e}"}

    if not text.strip():
        return {"status": "blocked", "reason": "file is empty"}

    summary = llm_generate(
        f"Explain this {path.suffix} file named {path.name}:\n\n{text}",
        system=EXPLAIN_SYSTEM,
    )
    if not summary:
        return {"status": "error", "reason": "explain model returned nothing"}

    return {
        "status": "success",
        "message": summary,
        "args": {"file": str(path), "chars_used": len(text)},
    }
