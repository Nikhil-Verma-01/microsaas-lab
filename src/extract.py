"""LLM problem extraction (Stage 2).

  python -m src.extract [--limit 50] [--rerun]

Reads:  data/raw.jsonl
Writes: data/problems.jsonl
Cache:  data/cache/extract/<doc_id>.json  (never re-pays for same doc)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import time
from pathlib import Path
from typing import Literal

from openai import OpenAI
from pydantic import BaseModel, ValidationError
from tqdm import tqdm

from .config import (
    EXTRACT_CACHE_DIR,
    EXTRACT_MODEL,
    LLM_API_KEY,
    LLM_BASE_URL,
    PROBLEMS_PATH,
    RAW_PATH,
)
from .pipeline.schema import ProductTrack

log = logging.getLogger(__name__)

# ── Schema ────────────────────────────────────────────────────────────────────

class ExtractedProblem(BaseModel):
    doc_id: str
    is_real_problem: bool = False
    tool_shaped: bool = False
    problem: str = ""                   # One concrete sentence
    user_type: str = "general users"    # e.g. "freelance designers", "small business owners"
    frequency: Literal["recurring", "one_off", "unknown"] = "unknown"
    current_workaround: str = ""
    pain_level: int = 3                 # 1–5
    existing_tools_mentioned: list[str] = []
    potential_automation: str = ""
    likely_search_query: str = ""       # what someone types into Google for this
    evidence_quote: str = ""            # <= 25 words, verbatim from the source text
    confidence: float = 0.5             # 0.0–1.0
    task_trigger: str = ""
    source: str = ""
    url: str = ""
    discussion_url: str = ""
    author: str = ""
    created_at: str = ""

# ── Prompt ────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """\
You are an expert micro-SaaS, web tool, and consumer/business utility opportunity researcher.
Your task is to analyze user evidence from real-world discussions (Reddit, Quora, forums, GitHub, Hacker News) and extract
concrete, real-world problems that could be solved by a standalone micro-SaaS, web app, calculator, converter, generator, checker, or free online utility
(monetizable via Google AdSense, affiliate, freemium subscription, or one-time micro-payments).

Output a valid JSON object matching these fields:
- "is_real_problem": (boolean) false if this is merely a localized bug report, personal rant, basic support question, or spam. True if it describes a real workflow friction, repetitive struggle, or unmet need.
- "tool_shaped": (boolean) true if a standalone tool, web utility, browser extension, or micro-SaaS could solve or automate this workflow. False if it requires massive physical infrastructure, deep human consulting, or is merely a complaint with no viable software solution.
- "problem": (string) A concise, concrete 1-sentence description of the general underlying user pain point or friction.
- "user_type": (string) The specific category of user experiencing this (e.g., "freelance designers", "small business owners", "content creators", "remote workers", "teachers", "accountants", "e-commerce sellers").
- "frequency": (string) "recurring", "one_off", or "unknown".
- "current_workaround": (string) How they currently cope (e.g., "manual copy-pasting", "Google Sheets formula", "hiring VA", "switching between 3 apps", "none").
- "pain_level": (integer, 1-5) 1=minor inconvenience, 3=regular friction/wasted hours, 5=critical blocker/loss of revenue.
- "existing_tools_mentioned": (list of strings) Existing tools, apps, or services cited in the text.
- "potential_automation": (string) What a micro-SaaS or standalone tool could automate or simplify.
- "likely_search_query": (string) What someone would type into Google to search for a solution (e.g. "free invoice pdf generator with client portal", "client call google doc automator", "daily kanban checklist collator").
- "evidence_quote": (string) A short verbatim snippet (<= 25 words) from the document capturing the core pain.
- "confidence": (float between 0.0 and 1.0) Confidence that this is a genuine, generalizable demand signal.
- "task_trigger": (string) What happened immediately before the user needed to perform the task, if stated.
Leave unstated workarounds and task triggers empty. Use unknown frequency unless the source says how often this person experiences the problem.
"""

def _load_cache(p: Path) -> ExtractedProblem | None:
    if p.exists():
        try:
            return ExtractedProblem.model_validate_json(p.read_text(encoding="utf-8"))
        except (OSError, ValidationError):
            pass
    return None


def extract_one(
    doc: dict, client: OpenAI, model: str, max_retries: int = 3, *,
    track: ProductTrack | None = None, force: bool = False,
) -> ExtractedProblem | None:
    doc_id = doc["id"]
    prompt = SYSTEM_PROMPT
    if track == ProductTrack.DEVELOPER:
        prompt += "\nAccept software development and technical operations workflows."
    elif track == ProductTrack.GENERAL:
        prompt += "\nAccept everyday and non-developer professional workflows, such as office or creator tasks."
    content = doc.get('text', '')
    cache_key = json.dumps([2, model, track, prompt, doc], sort_keys=True, ensure_ascii=False)
    digest = hashlib.sha256(cache_key.encode("utf-8")).hexdigest()
    cache_path = EXTRACT_CACHE_DIR / f"{digest}.json"
    cached = None if force else _load_cache(cache_path)
    if cached is not None:
        return cached

    user_content = f"Title: {doc.get('title', '')}\nSource URL: {doc.get('url', '')}\n\nContent:\n{content}"

    for attempt in range(max_retries):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": user_content},
                ],
                response_format={"type": "json_object"},
                temperature=0.1,
            )
            raw = response.choices[0].message.content or "{}"
            data = json.loads(raw)
            data["doc_id"] = doc_id
            for key in ("source", "url", "discussion_url", "author", "created_at"):
                data[key] = doc.get(key) or ""
            if "pain_level" in data:
                try:
                    data["pain_level"] = int(float(str(data["pain_level"]).split()[0]))
                except Exception:
                    data["pain_level"] = 3
            if "confidence" in data:
                try:
                    data["confidence"] = float(str(data["confidence"]).split()[0])
                except Exception:
                    data["confidence"] = 0.5
            if not isinstance(data.get("existing_tools_mentioned"), list):
                data["existing_tools_mentioned"] = [str(data.get("existing_tools_mentioned"))] if data.get("existing_tools_mentioned") else []
            prob = ExtractedProblem.model_validate(data)
            quote = " ".join(prob.evidence_quote.split())
            if len(quote.split()) > 25 or not any(
                quote and quote in " ".join(part.split()) for part in (content, doc.get("title", ""))
            ):
                prob.evidence_quote = ""
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(prob.model_dump_json(indent=2), encoding="utf-8")
            time.sleep(1.8)  # Polite pacing to stay under rate limits (e.g. 30 RPM)
            return prob
        except (json.JSONDecodeError, ValidationError) as exc:
            log.warning("parse error doc=%s attempt=%d: %s", doc_id, attempt, exc)
            time.sleep(2)
        except Exception as exc:
            err_str = str(exc)
            if "429" in err_str or "rate_limit" in err_str:
                wait_time = 10 * (attempt + 1)
                log.warning("Rate limit on doc=%s; sleeping %ds...", doc_id, wait_time)
                time.sleep(wait_time)
                continue
            log.error("API error doc=%s: %s", doc_id, exc)
            break
    return None

def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int, default=0, help="process only N docs (0=all)")
    ap.add_argument("--source", default="", help="filter docs by source/id prefix, e.g. 'web' or 'reddit'")
    ap.add_argument("--rerun", action="store_true", help="ignore cache and re-extract all")
    args = ap.parse_args()

    if not LLM_API_KEY:
        raise ValueError("No LLM API key found in .env (check GROQ_KEY or OPENAI_API_KEY).")

    client_kwargs = {"api_key": LLM_API_KEY}
    if LLM_BASE_URL:
        client_kwargs["base_url"] = LLM_BASE_URL
    client = OpenAI(**client_kwargs)

    if not RAW_PATH.exists():
        print(f"Error: {RAW_PATH} does not exist.")
        return

    docs = [json.loads(line) for line in RAW_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]
    if args.source:
        docs = [d for d in docs if args.source in d.get("source", "") or args.source in d.get("id", "")]
    if args.limit > 0:
        docs = docs[:args.limit]

    EXTRACT_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    PROBLEMS_PATH.parent.mkdir(parents=True, exist_ok=True)

    stats = {"total": len(docs), "extracted": 0, "filtered": 0, "errors": 0}

    # If rerun or starting fresh, open in write mode; otherwise load existing extracted doc_ids
    existing_ids = set()
    if PROBLEMS_PATH.exists() and not args.rerun:
        with PROBLEMS_PATH.open("r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    try:
                        existing_ids.add(json.loads(line)["doc_id"])
                    except Exception:
                        pass

    mode = "w" if args.rerun else "a"
    with PROBLEMS_PATH.open(mode, encoding="utf-8") as out:
        for doc in tqdm(docs, desc="extracting"):
            if doc["id"] in existing_ids:
                stats["extracted"] += 1
                continue

            prob = extract_one(doc, client, EXTRACT_MODEL, force=args.rerun)
            if prob is None:
                stats["errors"] += 1
                continue

            if not (prob.is_real_problem and prob.tool_shaped):
                stats["filtered"] += 1
                continue

            out.write(prob.model_dump_json() + "\n")
            out.flush()
            stats["extracted"] += 1

    print("\nExtraction Summary:")
    print(f"  Total processed: {stats['total']}")
    print(f"  Saved problems : {stats['extracted']}")
    print(f"  Filtered out   : {stats['filtered']}")
    print(f"  Errors         : {stats['errors']}")
    filter_pct = (stats['filtered'] / max(stats['total'], 1)) * 100
    print(f"  Filter rate    : {filter_pct:.1f}%")
    print(f"Output saved to  : {PROBLEMS_PATH}")

if __name__ == "__main__":
    main()
