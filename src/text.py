from __future__ import annotations

import html
import re
from datetime import datetime, timezone

from .config import MAX_TEXT_CHARS

_TAG = re.compile(r"<[^>]+>")
_HTML_COMMENT = re.compile(r"<!--.*?-->", re.S)
_CODE_FENCE = re.compile(r"```.*?```", re.S)
_URL = re.compile(r"https?://\S+")
_SPACES = re.compile(r"[ \t]+")
_BLANKS = re.compile(r"\n{3,}")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def strip_html(s: str) -> str:
    s = re.sub(r"(?i)<\s*(br|p|/p)\s*/?>", "\n", s)
    s = _TAG.sub("", s)
    return html.unescape(s)


def clean_text(s: str, max_chars: int = MAX_TEXT_CHARS) -> str:
    """Remove issue-template comments, code blocks (stack traces), and URLs."""
    s = _HTML_COMMENT.sub("", s)
    s = _CODE_FENCE.sub("[code omitted]", s)
    s = _URL.sub("", s)
    s = _SPACES.sub(" ", s)
    s = _BLANKS.sub("\n\n", s).strip()
    return s[:max_chars]


def quote_if_needed(term: str) -> str:
    term = term.strip()
    return f'"{term}"' if " " in term else term
