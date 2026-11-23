from __future__ import annotations

from pydantic import BaseModel


class Document(BaseModel):
    """One piece of evidence, normalized across sources."""

    id: str                 # "<source>:<native id>", globally unique
    source: str            # github | hn | web
    kind: str              # issue | story | comment | page
    url: str
    discussion_url: str = ""  # Parent discussion if this document is a comment
    title: str = ""
    text: str              # title + body, cleaned and truncated
    author: str = ""
    created_at: str = ""   # ISO 8601
    score: int = 0         # GitHub reactions / HN points (demand signal)
    comments: int = 0
    community: str = ""    # repo full name, or "hacker-news"
    query: str = ""        # exact search query that found it
    keyword: str = ""      # niche keyword that seeded the query
    collected_at: str = ""
