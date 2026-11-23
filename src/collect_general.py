"""General Web & Community Collector for Everyday Pain Points.

Discovers user problems across Reddit, Quora, and community forums using static browsing/search
and Scrapling fetchers, normalizing into Document models for the micro-SaaS lab pipeline.

Usage:
  python -m src.collect_general --niches productivity freelance creators office quora --limit 30
  python -m src.collect_general --queries '"is there a tool for" site:reddit.com' '"is there a tool for" site:quora.com' --limit 20
  python -m src.collect_general --dry-run
"""
from __future__ import annotations

import argparse
import hashlib
import logging
import re
import sys
import time
from datetime import datetime, timezone
from urllib.parse import quote_plus, unquote, urlparse
from typing import Iterator

from .config import MIN_TEXT_CHARS, RAW_PATH
from .schema import Document
from .store import load_ids
from .text import clean_text, now_iso, strip_html

try:
    from scrapling.fetchers import Fetcher, StealthyFetcher
    _SCRAPLING_AVAILABLE = True
except ImportError:
    Fetcher = None
    StealthyFetcher = None
    _SCRAPLING_AVAILABLE = False

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

log = logging.getLogger(__name__)

# Predefined niche query suites for non-developer everyday pain points
NICHE_QUERIES = {
    "productivity": [
        '"is there a tool for" site:reddit.com/r/productivity',
        '"is there an app for" site:reddit.com/r/productivity',
        '"is there a website that" site:reddit.com/r/productivity',
        '"looking for a tool that" site:reddit.com/r/productivity',
        '"wish there was a tool" site:reddit.com/r/productivity',
    ],
    "freelance": [
        '"is there a tool for" site:reddit.com/r/freelance',
        '"is there a tool for" site:reddit.com/r/Entrepreneur',
        '"is there a tool for" site:reddit.com/r/smallbusiness',
        '"is there an app to" site:reddit.com/r/freelance',
        '"looking for a tool that" site:reddit.com/r/Entrepreneur',
        '"is there a tool for" site:reddit.com/r/ecommerce',
    ],
    "creators": [
        '"is there a tool for" site:reddit.com/r/VideoEditing',
        '"is there a tool that" site:reddit.com/r/content_marketing',
        '"is there a tool for" site:reddit.com/r/socialmedia',
        '"is there an online tool" site:reddit.com/r/podcasts',
        '"is there a free tool" site:reddit.com/r/VideoEditing',
    ],
    "office": [
        '"is there a tool for" site:reddit.com/r/excel',
        '"is there a tool to" site:reddit.com/r/accounting',
        '"is there an online tool to" site:reddit.com/r/personalfinance',
        '"is there a tool for" site:reddit.com/r/notion',
    ],
    "quora": [
        '"is there a tool for" site:quora.com',
        '"is there an app for" site:quora.com',
        '"is there a website that" site:quora.com',
        '"is there a free online tool" site:quora.com',
        '"is there a tool to" site:quora.com',
    ],
    "forums": [
        '"is there a tool for" site:community.spiceworks.com',
        '"is there a tool that" site:community.spiceworks.com',
        '"is there a tool for" site:news.ycombinator.com',
    ],
}


def search_engine_urls(query: str, max_results: int = 10) -> list[dict]:
    """Discover discussion URLs for query using Yahoo search via Scrapling Fetcher."""
    clean_q = query.replace("{", "").replace("}", "").strip()
    search_url = f"https://search.yahoo.com/search?p={quote_plus(clean_q)}"
    results = []

    try:
        page = Fetcher.get(search_url, timeout=15)
        if page and page.status == 200:
            for li in page.css("ol.searchCenterMiddle li, div#web li, div.compText"):
                h3 = li.css("h3")
                a = li.css("a")
                if not (h3 and a):
                    continue
                title = h3[0].get_all_text().strip()
                raw_href = a[0].attrib.get("href", "")
                
                # Yahoo search result redirection decoding
                m = re.search(r'/RU=([^/]+)/', raw_href)
                target_url = unquote(m.group(1)) if m else raw_href

                # Snippet description
                comp_text = li.css("div.compText, p, span.lh-16")
                snippet = comp_text[0].get_all_text().strip() if comp_text else ""

                # Ignore search noise
                if not target_url.startswith("http") or "search.yahoo.com" in target_url or "login.yahoo" in target_url:
                    continue
                if any(x in target_url for x in ["help.quora.com", "redditinc.com", "business.reddit.com", "reddithelp.com"]):
                    continue

                results.append({
                    "title": title,
                    "url": target_url,
                    "snippet": snippet,
                })
                if len(results) >= max_results:
                    break
    except Exception as exc:
        log.warning("Yahoo search error for query '%s': %s", clean_q, exc)

    return results


def _clean_reddit_body(raw_text: str) -> str:
    """Strip boilerplate Reddit navigation text from page body."""
    lines = raw_text.splitlines()
    cleaned = []
    ignore_prefixes = (
        "reddit - the heart", "skip to", "open menu", "open navigation",
        "go to reddit", "sign up", "sign in", "log in", "expand user",
        "open settings", "top posts", "popular", "explore", "best of",
        "reddit rules", "privacy policy", "user agreement", "accessibility",
        "join the most", "continue with", "by continuing", "anyone can view",
        "share", "public", "read more", "•"
    )
    for line in lines:
        stripped = line.strip()
        low = stripped.lower()
        if not stripped:
            continue
        if any(low.startswith(p) for p in ignore_prefixes):
            continue
        cleaned.append(stripped)
    return "\n\n".join(cleaned)


def scrape_discussion(url: str, title_hint: str = "", snippet_hint: str = "") -> dict:
    """Scrape and parse discussion thread using Scrapling."""
    out = {
        "url": url,
        "title": title_hint,
        "text": snippet_hint,
        "author": "",
        "community": "",
        "score": 0,
        "comments": 0,
        "source": "web",
    }
    parsed = urlparse(url)
    domain = parsed.netloc.lower()

    if "reddit.com" in domain:
        out["source"] = "reddit"
        try:
            page = Fetcher.get(url, timeout=20)
            if page and page.status == 200:
                # Try shreddit-post attributes
                posts = page.css("shreddit-post")
                if posts:
                    p = posts[0]
                    out["title"] = p.attrib.get("post-title") or out["title"]
                    out["author"] = p.attrib.get("author") or ""
                    out["community"] = p.attrib.get("subreddit-prefixed-name") or "reddit"
                    try:
                        out["score"] = int(p.attrib.get("score") or 0)
                    except ValueError:
                        out["score"] = 0
                    try:
                        out["comments"] = int(p.attrib.get("comment-count") or 0)
                    except ValueError:
                        out["comments"] = 0

                # Extract post body
                body_els = page.css("div[slot='text-body'], div.text-neutral-content")
                if body_els:
                    out["text"] = body_els[0].get_all_text().strip()
                else:
                    all_txt = page.get_all_text()
                    out["text"] = _clean_reddit_body(all_txt)

                # Fallback: if body is too short or post was deleted, augment with hints
                if len(out["text"]) < MIN_TEXT_CHARS:
                    out["text"] = f"{out['title']}\n\n{snippet_hint}\n\n{out['text']}".strip()
        except Exception as exc:
            log.debug("Scrapling Reddit fetch failed for %s: %s", url, exc)

    elif "quora.com" in domain:
        out["source"] = "quora"
        out["community"] = "quora"
        try:
            # First try plain Fetcher
            page = Fetcher.get(url, timeout=15)
            text = page.get_all_text() if page and page.status == 200 else ""
            
            # If Quora prompts for JS or error, use StealthyFetcher
            if ("Please enable Javascript" in text or len(text) < 300) and StealthyFetcher is not None:
                log.info("Quora JS challenge detected; using StealthyFetcher for %s", url)
                page = StealthyFetcher.fetch(url, timeout=25000)
                text = page.get_all_text() if page else ""

            if text:
                # Title
                t_match = re.search(r"^(.*?)(?:\s*-\s*Quora)?$", title_hint)
                out["title"] = t_match.group(1).strip() if t_match else title_hint
                # Clean text
                lines = [l.strip() for l in text.splitlines() if len(l.strip()) > 20]
                out["text"] = "\n\n".join(lines[:15]) if lines else snippet_hint
        except Exception as exc:
            log.debug("Quora fetch failed for %s: %s", url, exc)

    else:
        # General forums / community websites (Spiceworks, etc.)
        out["source"] = "web"
        out["community"] = domain.replace("www.", "")
        try:
            page = Fetcher.get(url, timeout=20)
            if page and page.status == 200:
                h1 = page.css("h1")
                if h1:
                    out["title"] = h1[0].get_all_text().strip()
                all_text = page.get_all_text()
                lines = [l.strip() for l in all_text.splitlines() if len(l.strip()) > 30]
                out["text"] = "\n\n".join(lines[:12]) if lines else snippet_hint
        except Exception as exc:
            log.debug("Web fetch failed for %s: %s", url, exc)

    return out


def collect_general(
    queries: list[str],
    per_query: int = 10,
    max_total: int = 50,
) -> Iterator[Document]:
    """Generator yielding normalized Document records from web searches and Scrapling."""
    seen_urls = set()
    collected_count = 0

    for query in queries:
        if collected_count >= max_total:
            break

        clean_q = query.replace("{", "").replace("}", "").strip()
        log.info("Searching query: %s", clean_q)
        hits = search_engine_urls(clean_q, max_results=per_query)

        for hit in hits:
            if collected_count >= max_total:
                break

            url = hit["url"]
            if url in seen_urls:
                continue
            seen_urls.add(url)

            # Scrape content using Scrapling
            disc = scrape_discussion(url, title_hint=hit["title"], snippet_hint=hit["snippet"])
            full_text = clean_text(f"{disc['title']}\n\n{disc['text']}")

            if len(full_text) < MIN_TEXT_CHARS:
                continue

            doc_id = f"web:{hashlib.sha256(url.encode('utf-8')).hexdigest()[:16]}"
            doc = Document(
                id=doc_id,
                source=disc["source"],
                kind="post",
                url=url,
                title=disc["title"],
                text=full_text,
                author=disc["author"],
                created_at="",
                score=disc["score"],
                comments=disc["comments"],
                community=disc["community"] or disc["source"],
                query=clean_q,
                keyword=clean_q.split()[0].replace('"', ''),
                collected_at=now_iso(),
            )
            collected_count += 1
            yield doc
            time.sleep(0.5)  # Friendly pacing between pages


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--niches", nargs="+", choices=list(NICHE_QUERIES.keys()), default=["productivity", "freelance", "creators", "office", "quora"])
    p.add_argument("--queries", nargs="+", default=[], help="custom queries, e.g. '{\"is there a tool for\" site:reddit.com}'")
    p.add_argument("--per-query", type=int, default=8, help="max results to inspect per search query")
    p.add_argument("--limit", type=int, default=30, help="maximum total new documents to collect")
    p.add_argument("--dry-run", action="store_true", help="print query plan and exit")
    return p.parse_args()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = parse_args()

    # Build query list
    query_list = []
    if args.queries:
        query_list.extend(args.queries)
    else:
        for niche in args.niches:
            query_list.extend(NICHE_QUERIES.get(niche, []))

    if args.dry_run:
        print(f"\nWEB COLLECTOR QUERY PLAN ({len(query_list)} queries):")
        for q in query_list:
            print("  ", q)
        return

    seen = load_ids()
    print(f"{len(seen)} documents currently in {RAW_PATH.name}")

    new_docs = 0
    with RAW_PATH.open("a", encoding="utf-8") as out:
        for doc in collect_general(query_list, per_query=args.per_query, max_total=args.limit):
            if doc.id in seen:
                continue
            seen.add(doc.id)
            out.write(doc.model_dump_json() + "\n")
            out.flush()
            new_docs += 1
            print(f"[{new_docs}/{args.limit}] {doc.source.upper()} ({doc.community}): {doc.title[:75]}")

    print(f"\nDone! Added {new_docs} new real-world pain point documents into {RAW_PATH}.")
    print(f"Total documents in file: {len(seen)}.")


if __name__ == "__main__":
    main()
