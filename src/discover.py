"""Run evidence-led discovery for one product track."""
from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from openai import OpenAI
from pydantic import TypeAdapter

from .config import (
    DATA_DIR, EXTRACT_MODEL, IDEATE_MODEL, LLM_API_KEY, LLM_BASE_URL, LLM_TIMEOUT, RAW_PATH,
)
from .extract import extract_one
from .pipeline.hypothesize import generate_hypotheses_for_cluster
from .pipeline.orchestrator import evaluate_candidate, generate_pipeline_reports
from .pipeline.schema import MarketEvidence, ProductTrack

log = logging.getLogger(__name__)
DEVELOPER_SOURCES = {"github", "hn"}


def discussion_key(url: str) -> tuple[str, str, str]:
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    parts = parsed.path.strip("/").split("/")
    if host in {"reddit.com", "old.reddit.com", "new.reddit.com"} and "comments" in parts:
        index = parts.index("comments") + 1
        if index < len(parts):
            return "reddit.com", parts[index], ""
    query = parsed.query
    if host == "news.ycombinator.com":
        query = parse_qs(query).get("id", [""])[0]
    return host, parsed.path.rstrip("/"), query


def group_problems(problems: list[dict], model: str, threshold: float) -> list[dict]:
    """Group problems by audience, task and trigger, retaining isolated leads."""
    labels = range(len(problems))
    if len(problems) > 1:
        from sentence_transformers import SentenceTransformer
        from sklearn.cluster import AgglomerativeClustering

        texts = [
            f"{p['user_type']} | {p['problem']} | {p['task_trigger']}"
            for p in problems
        ]
        embeddings = SentenceTransformer(model).encode(texts, normalize_embeddings=True)
        labels = AgglomerativeClustering(
            n_clusters=None, distance_threshold=threshold, metric="cosine", linkage="complete",
        ).fit_predict(embeddings)

    groups = {}
    for label, problem in zip(labels, problems):
        groups.setdefault(int(label), []).append(problem)

    clusters = []
    for cluster_id, members in enumerate(groups.values()):
        representatives = []
        seen_authors = set()
        seen_urls = set()
        for p in members:
            author = (p["source"], p["author"].strip().casefold())
            url_key = discussion_key(p.get("discussion_url") or p["url"])
            if author[1] and author not in seen_authors and url_key not in seen_urls:
                representatives.append(p)
                seen_authors.add(author)
                seen_urls.add(url_key)
        clusters.append({
            "id": cluster_id,
            "name": members[0]["problem"],
            "member_count": len(members),
            "members": [p["doc_id"] for p in members],
            "independent_evidence": len(representatives),
            "representatives": [p["doc_id"] for p in representatives],
            "user_types": list(dict.fromkeys(p["user_type"] for p in members)),
            "sample_workarounds": list(dict.fromkeys(p["current_workaround"] for p in members if p["current_workaround"])),
            "search_queries": list(dict.fromkeys(p["likely_search_query"] for p in members if p["likely_search_query"])),
        })
    return sorted(clusters, key=lambda c: -c["independent_evidence"])


def run(args: argparse.Namespace) -> None:
    track = ProductTrack(args.track)
    raw_path = args.raw or RAW_PATH
    with raw_path.open(encoding="utf-8") as source:
        documents = [json.loads(line) for line in source if line.strip()]
    if args.raw is None:
        documents = [
            d for d in documents
            if (d.get("source") in DEVELOPER_SOURCES) == (track == ProductTrack.DEVELOPER)
        ]
    docs = list({d["id"]: d for d in documents}.values())
    if args.limit:
        docs = docs[:args.limit]

    market_evidence = {}
    if args.market_evidence:
        market_evidence = TypeAdapter(dict[str, MarketEvidence]).validate_json(
            args.market_evidence.read_bytes()
        )

    problems = []
    errors = 0
    client = None
    if docs:
        if not LLM_API_KEY:
            raise ValueError("Configure an LLM provider before running discovery.")
        client = OpenAI(base_url=LLM_BASE_URL, api_key=LLM_API_KEY, timeout=LLM_TIMEOUT)
    for doc in docs:
        extracted = extract_one(doc, client, EXTRACT_MODEL, track=track, force=args.force)
        if extracted is None:
            errors += 1
        elif extracted.is_real_problem and extracted.tool_shaped and extracted.evidence_quote and extracted.url and extracted.problem.strip():
            problems.append(extracted.model_dump())

    clusters = group_problems(problems, args.embedding_model, args.distance_threshold)
    eligible = [c for c in clusters if c["independent_evidence"] >= 2]
    problems_by_id = {p["doc_id"]: p for p in problems}
    decisions, hypotheses, wedges, mvps, gtms = [], {}, {}, {}, {}
    failed_clusters = []
    for cluster in eligible[:args.top_n]:
        member_problems = [problems_by_id[doc_id] for doc_id in cluster["representatives"]]
        result = generate_hypotheses_for_cluster(
            cluster, member_problems, client, force=args.force, model=args.model, track=track,
        )
        if result is None:
            failed_clusters.append(cluster["id"])
            continue
        for hypothesis in result.hypotheses:
            key = hypothesis.opportunity_id
            decision, wedge, mvp, gtm = evaluate_candidate(
                hypothesis, client, force=True, model=args.model, market_evidence=market_evidence.get(key),
            )
            decisions.append(decision)
            hypotheses[key] = hypothesis
            wedges[key] = wedge
            if mvp:
                mvps[key] = mvp
            if gtm:
                gtms[key] = gtm

    out = DATA_DIR / "discovery" / track.value
    out.mkdir(parents=True, exist_ok=True)
    summary = {
        "track": track.value,
        "input": str(raw_path),
        "input_documents": len(docs),
        "extraction_errors": errors,
        "verified_problems": len(problems),
        "eligible_clusters": len(eligible),
        "failed_hypothesis_clusters": failed_clusters,
        "clusters": clusters,
    }
    (out / "problems.jsonl").write_text(
        "".join(json.dumps(p, ensure_ascii=False) + "\n" for p in problems), encoding="utf-8",
    )
    (out / "clusters.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    generate_pipeline_reports(
        decisions, hypotheses, wedges, mvps, gtms, out / "report.md", out / "scores.csv",
        market_evidence=market_evidence,
        run_summary=(
            f"**Track:** {track.value}  \n"
            f"**Run:** {len(docs)} documents, {len(problems)} grounded problems, "
            f"{len(eligible)} eligible groups, {errors} extraction errors, "
            f"{len(failed_clusters)} hypothesis generation errors.\n"
        ),
    )
    log.info(
        "%s: %d documents, %d grounded problems, %d eligible groups, %d ideas, %d extraction errors",
        track.value, len(docs), len(problems), len(eligible), len(decisions), errors,
    )


def main(default_track: ProductTrack | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--track", choices=[t.value for t in ProductTrack], required=default_track is None, default=default_track)
    parser.add_argument("--raw", type=Path, help="Use a track-specific input JSONL without source filtering")
    parser.add_argument("--limit", type=int, default=0, help="Maximum documents, or 0 for all")
    parser.add_argument("--top-n", type=int, default=5, help="Maximum eligible problem groups to develop")
    parser.add_argument("--model", default=IDEATE_MODEL, help="Model override for hypotheses and evaluation")
    parser.add_argument("--embedding-model", default="BAAI/bge-small-en-v1.5")
    parser.add_argument("--distance-threshold", type=float, default=0.30)
    parser.add_argument("--market-evidence", type=Path, help="Reviewed evidence JSON keyed by opportunity ID")
    parser.add_argument("--force", action="store_true", help="Refresh cached extraction and hypotheses")
    args = parser.parse_args()
    if args.limit < 0 or args.top_n < 0 or not 0 < args.distance_threshold <= 2:
        parser.error("limits must be nonnegative and distance threshold must be in (0, 2]")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    run(args)


if __name__ == "__main__":
    main()
