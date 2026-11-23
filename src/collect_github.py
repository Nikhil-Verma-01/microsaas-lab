"""GitHub issue collector (official Search API).

Search API limits: 30 req/min authenticated (10 unauthenticated) and only the
first 1,000 results per query. So: many specific queries beat one broad one.
Reactions + comment counts come back for free and are a real demand signal.
"""
from __future__ import annotations

import logging
import time
from typing import Iterator

import httpx
from tqdm import tqdm

from .config import GITHUB_TOKEN, MIN_TEXT_CHARS
from .http_util import get_json
from .schema import Document
from .text import clean_text, now_iso, quote_if_needed

log = logging.getLogger(__name__)

SEARCH_URL = "https://api.github.com/search/issues"
REPO_PREFIX = "https://api.github.com/repos/"


def plan_queries(
    keywords: list[str], phrases: list[str], since: str | None = None, extra: str = ""
) -> list[tuple[str, str]]:
    """Return [(query, keyword)] = every pain phrase x every niche keyword."""
    plan = []
    for kw in keywords:
        for phrase in phrases:
            q = f'"{phrase}" {quote_if_needed(kw)} is:issue in:title,body'
            if since:
                q += f" created:>={since}"
            if extra:
                q += f" {extra}"
            plan.append((q, kw))
    return plan


def to_document(item: dict, query: str, keyword: str) -> Document | None:
    if "pull_request" in item:
        return None
    user = item.get("user") or {}
    login = user.get("login", "")
    if user.get("type") == "Bot" or login.endswith("[bot]"):
        return None

    title = item.get("title") or ""
    body = item.get("body") or ""
    text = clean_text(f"{title}\n\n{body}")
    if len(text) < MIN_TEXT_CHARS:
        return None

    repo = (item.get("repository_url") or "").replace(REPO_PREFIX, "")
    return Document(
        id=f"github:{item['id']}",
        source="github",
        kind="issue",
        url=item.get("html_url", ""),
        title=title,
        text=text,
        author=login,
        created_at=item.get("created_at", ""),
        score=(item.get("reactions") or {}).get("total_count", 0),
        comments=item.get("comments", 0),
        community=repo,
        query=query,
        keyword=keyword,
        collected_at=now_iso(),
    )


def collect_github(
    client: httpx.Client,
    keywords: list[str],
    phrases: list[str],
    per_query: int = 100,
    since: str | None = None,
    extra: str = "",
    sort: str = "reactions",
) -> Iterator[Document]:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"
    else:
        log.warning("No GITHUB_TOKEN set: limited to ~10 search requests/min.")
    delay = 2.5 if GITHUB_TOKEN else 7.0

    per_page = min(100, per_query)
    pages = -(-per_query // per_page)

    for query, keyword in tqdm(plan_queries(keywords, phrases, since, extra), desc="github"):
        for page in range(1, pages + 1):
            params = {"q": query, "per_page": per_page, "page": page, "sort": sort, "order": "desc"}
            data = get_json(client, SEARCH_URL, params=params, headers=headers)
            time.sleep(delay)
            items = (data or {}).get("items") or []
            for item in items:
                doc = to_document(item, query, keyword)
                if doc:
                    yield doc
            if len(items) < per_page:
                break
