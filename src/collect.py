"""Run collectors and append deduplicated evidence to data/raw.jsonl.

Examples
  python -m src.collect --keywords csv excel reconcile --sources github hn --dry-run
  python -m src.collect --keywords csv excel reconcile --sources github hn \
      --per-query 50 --max-phrases 6 --since 2023-01-01 --limit-per-source 300
  python -m src.collect --keywords openapi --sources github --gh-extra "label:enhancement"
"""
from __future__ import annotations

import argparse
import logging
from collections import Counter

import httpx

from . import collect_general, collect_github, collect_hn
from .config import PAIN_PHRASES, RAW_PATH, USER_AGENT
from .store import load_ids


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--keywords", nargs="+", required=True, help="niche seed terms, e.g. csv openapi 'api docs'")
    p.add_argument("--sources", nargs="+", choices=["github", "hn", "web"], default=["github", "hn", "web"])
    p.add_argument("--per-query", type=int, default=50, help="max results fetched per query")
    p.add_argument("--max-phrases", type=int, default=len(PAIN_PHRASES))
    p.add_argument("--since", help="only items created on/after YYYY-MM-DD")
    p.add_argument("--limit-per-source", type=int, default=500, help="stop a source after N NEW docs")
    p.add_argument("--gh-extra", default="", help='extra GitHub qualifiers, e.g. "label:enhancement"')
    p.add_argument("--gh-sort", default="reactions", choices=["reactions", "comments", "created", "updated"])
    p.add_argument("--hn-tags", nargs="+", default=["ask_hn", "comment"])
    p.add_argument("--dry-run", action="store_true", help="print the query plan and exit")
    return p.parse_args()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    args = parse_args()
    phrases = PAIN_PHRASES[: args.max_phrases]

    if args.dry_run:
        if "github" in args.sources:
            plan = collect_github.plan_queries(args.keywords, phrases, args.since, args.gh_extra)
            print(f"\nGITHUB: {len(plan)} queries (~{len(plan) * 3}s at token rate limits)")
            for q, _ in plan[:15]:
                print("  ", q)
        if "hn" in args.sources:
            plan = collect_hn.plan_queries(args.keywords, phrases)
            print(f"\nHN: {len(plan)} queries x {len(args.hn_tags)} tags")
            for q, _ in plan[:15]:
                print("  ", q)
        return

    seen = load_ids()
    print(f"{len(seen)} documents already in {RAW_PATH.name}")
    stats: Counter = Counter()

    with httpx.Client(timeout=30, headers={"User-Agent": USER_AGENT}, follow_redirects=True) as client, \
         RAW_PATH.open("a", encoding="utf-8") as out:

        streams = {}
        if "github" in args.sources:
            streams["github"] = collect_github.collect_github(
                client, args.keywords, phrases, args.per_query, args.since, args.gh_extra, args.gh_sort
            )
        if "hn" in args.sources:
            streams["hn"] = collect_hn.collect_hn(
                client, args.keywords, phrases, args.per_query, args.since, tuple(args.hn_tags)
            )
        if "web" in args.sources:
            web_queries = [f'"{p}" {k}' for k in args.keywords for p in phrases]
            streams["web"] = collect_general.collect_general(
                web_queries, per_query=args.per_query, max_total=args.limit_per_source
            )

        for source, stream in streams.items():
            for doc in stream:
                if doc.id in seen:
                    stats[f"{source}_dupes"] += 1
                    continue
                seen.add(doc.id)
                out.write(doc.model_dump_json() + "\n")
                out.flush()
                stats[f"{source}_new"] += 1
                if stats[f"{source}_new"] >= args.limit_per_source:
                    print(f"{source}: reached limit of {args.limit_per_source} new docs")
                    break

    print("\nSummary:")
    for k in sorted(stats):
        print(f"  {k}: {stats[k]}")
    print(f"Total in file: {len(seen)}  ->  {RAW_PATH}")


if __name__ == "__main__":
    main()
