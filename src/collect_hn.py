"""Hacker News collector (Algolia HN Search API: free, no auth).

Best tags for demand discovery:
  ask_hn  -> "Ask HN: Is there a tool for ...?" threads
  comment -> people describing their own workflows and workarounds
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Iterator

import httpx
from tqdm import tqdm

from .config import MIN_TEXT_CHARS
from .http_util import get_json
from .schema import Document
from .text import clean_text, now_iso, quote_if_needed, strip_html

log = logging.getLogger(__name__)

SEARCH_URL = "https://hn.algolia.com/api/v1/search"
ITEM_URL = "https://news.ycombinator.com/item?id={}"


def plan_queries(keywords: list[str], phrases: list[str]) -> list[tuple[str, str]]:
    return [(f'"{p}" {quote_if_needed(k)}', k) for k in keywords for p in phrases]


def to_document(hit: dict, query: str, keyword: str) -> Document | None:
    is_comment = "comment" in (hit.get("_tags") or [])
    raw = hit.get("comment_text") if is_comment else hit.get("story_text")
    body = strip_html(raw or "")
    title = hit.get("story_title") if is_comment else hit.get("title")
    title = title or ""
    text = clean_text(f"{title}\n\n{body}" if title else body)
    if len(text) < MIN_TEXT_CHARS:
        return None

    oid = hit.get("objectID")
    if not oid:
        return None
    return Document(
        id=f"hn:{oid}",
        source="hn",
        kind="comment" if is_comment else "story",
        url=ITEM_URL.format(oid),
        discussion_url=ITEM_URL.format(hit.get("story_id") or oid),
        title=title,
        text=text,
        author=hit.get("author") or "",
        created_at=hit.get("created_at") or "",
        score=hit.get("points") or 0,
        comments=hit.get("num_comments") or 0,
        community="hacker-news",
        query=query,
        keyword=keyword,
        collected_at=now_iso(),
    )


def collect_hn(
    client: httpx.Client,
    keywords: list[str],
    phrases: list[str],
    per_query: int = 100,
    since: str | None = None,
    tags: tuple[str, ...] = ("ask_hn", "comment"),
) -> Iterator[Document]:
    since_ts = None
    if since:
        since_ts = int(datetime.strptime(since, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())

    hits_per_page = min(100, per_query)
    max_pages = -(-per_query // hits_per_page)

    for query, keyword in tqdm(plan_queries(keywords, phrases), desc="hn"):
        for tag in tags:
            for page in range(max_pages):
                params = {"query": query, "tags": tag, "hitsPerPage": hits_per_page, "page": page}
                if since_ts:
                    params["numericFilters"] = f"created_at_i>{since_ts}"
                data = get_json(client, SEARCH_URL, params=params)
                time.sleep(0.3)
                hits = (data or {}).get("hits") or []
                for hit in hits:
                    doc = to_document(hit, query, keyword)
                    if doc:
                        yield doc
                if not data or page + 1 >= data.get("nbPages", 0):
                    break
