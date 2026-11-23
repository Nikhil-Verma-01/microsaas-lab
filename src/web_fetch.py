"""Fetch web pages with Scrapling and extract competitor signals (Day 5 check).

Use this for the "do good tools already exist?" step and for sites with no API.
It is NOT for collecting content you will republish.

Setup:  pip install "scrapling[fetchers]"
        (plain Fetcher needs nothing else; DynamicFetcher/StealthyFetcher need
         `scrapling install` for browsers. Check the Scrapling docs, the API moves.)

Usage:  python -m src.web_fetch https://example.com/tool https://other.com
"""
from __future__ import annotations

import json
import re
import sys
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

from .config import USER_AGENT
from .text import strip_html

try:
    from scrapling.fetchers import Fetcher
    _IMPORT_ERROR = None
except ImportError as _exc:  # keeps the rest of the project importable
    Fetcher = None
    _IMPORT_ERROR = str(_exc)

_SCRIPT_STYLE = re.compile(r"(?is)<(script|style|noscript).*?</\1>")
_TITLE = re.compile(r"(?is)<title[^>]*>(.*?)</title>")
_PRICE = re.compile(r"\$\s?\d{1,4}(?:[.,]\d{2})?(?:\s?/\s?(?:mo|month|yr|year))?", re.I)
_YEAR = re.compile(r"(?:©|&copy;|copyright)\s*(?:\d{4}\s*[-–]\s*)?(20\d{2})", re.I)

ENTERPRISE_MARKERS = ["contact sales", "book a demo", "request a demo", "talk to sales", "enterprise"]
FREE_MARKERS = ["free plan", "free forever", "no signup", "no sign-up", "free tier", "try it free", "free online"]


def allowed_by_robots(url: str) -> bool:
    """Respect robots.txt. If it can't be read, be conservative and say no."""
    parts = urlparse(url)
    rp = RobotFileParser()
    rp.set_url(f"{parts.scheme}://{parts.netloc}/robots.txt")
    try:
        rp.read()
    except Exception:
        return False
    return rp.can_fetch(USER_AGENT, url)


def _html_of(page) -> str:
    for attr in ("html_content", "body"):
        val = getattr(page, attr, None)
        if val:
            return val.decode("utf-8", "ignore") if isinstance(val, bytes) else str(val)
    return str(page)


def fetch(url: str) -> dict:
    """Return {url, status, title, text, html_len, error}."""
    out = {"url": url, "status": None, "title": "", "text": "", "html_len": 0, "error": None}
    if Fetcher is None:
        out["error"] = f"scrapling import failed ({_IMPORT_ERROR}); run: pip install \"scrapling[fetchers]\""
        return out
    if not allowed_by_robots(url):
        out["error"] = "blocked by robots.txt (or robots.txt unreadable)"
        return out
    try:
        page = Fetcher.get(url, timeout=20)
        html = _html_of(page)
        out.update(status=getattr(page, "status", None), html_len=len(html))
        m = _TITLE.search(html)
        out["title"] = strip_html(m.group(1)).strip() if m else ""
        out["text"] = re.sub(r"\s+", " ", strip_html(_SCRIPT_STYLE.sub(" ", html))).strip()
    except Exception as exc:  # network, TLS, parse...
        out["error"] = f"{type(exc).__name__}: {exc}"
    return out


def competitor_snapshot(url: str) -> dict:
    """Cheap signals for 'is this competitor weak or strong, free or enterprise?'"""
    r = fetch(url)
    if r["error"] or not r["text"]:
        return {"url": url, "error": r["error"] or "empty page"}
    low = r["text"].lower()
    years = [int(y) for y in _YEAR.findall(r["text"])]
    return {
        "url": url,
        "title": r["title"],
        "status": r["status"],
        "word_count": len(r["text"].split()),
        "latest_copyright_year": max(years) if years else None,  # old year = stale product
        "enterprise_heavy": [m for m in ENTERPRISE_MARKERS if m in low],
        "free_signals": [m for m in FREE_MARKERS if m in low],
        "prices_seen": list(dict.fromkeys(_PRICE.findall(r["text"])))[:6],
    }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    for u in sys.argv[1:]:
        print(json.dumps(competitor_snapshot(u), indent=2))
