"""Stage 2: Multi-Archetype Solution Hypothesis Generator.

Reads:  data/clusters.json + data/problems.jsonl
Writes: data/cache/hypotheses/cluster_{id}.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
from pathlib import Path
from typing import Optional

from openai import OpenAI
from pydantic import ValidationError

from ..config import (
    CLUSTERS_PATH,
    HYPOTHESIS_CACHE_DIR,
    IDEATE_MODEL,
    LLM_API_KEY,
    LLM_BASE_URL,
    LLM_TIMEOUT,
    PROBLEMS_PATH,
)
from .schema import (
    EvidenceRecord,
    ProductTrack,
    HypothesisSet,
    ProblemContext,
    ProductArchetype,
    SolutionHypothesis,
)

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

log = logging.getLogger(__name__)

HYPOTHESIZE_SYSTEM = """\
You are an expert developer-tool architect and micro-SaaS strategist for an indie engineer.
Your goal is to generate 3 to 5 DISTINCT, high-conviction product hypotheses for a validated developer problem cluster.

CRITICAL RULES TO AVOID BLAND & DRIFTING OUTPUT:
1. STRICT DOMAIN GROUNDING (NO DRIFT):
   - You MUST generate solutions directly addressing the exact developer pain points, technologies, and verbatim quotes provided.
   - NEVER drift into unrelated domains (e.g., if quotes discuss OpenAPI/Swagger, all solutions MUST address OpenAPI/Swagger; NEVER generate CSV or resume tools).

2. ANTI-BLAND ARCHETYPE DIVERSITY (NO MODE COLLAPSE):
   - Do NOT default to generic "single-page web app with a split-pane" solutions.
   - Your 3 to 5 hypotheses MUST span AT LEAST 3 DIFFERENT structural archetypes from:
     * "in_situ_devflow": Developer works in git/terminal/CI without tab-switching (CLI, GitHub Action, pre-commit hook, IDE/LSP extension).
     * "headless_middleware": Background daemon, local proxy, or webhook gateway that intercepts and transforms traffic.
     * "zero_data_client_wasm": Client-only in-memory browser utility where code/data NEVER touches a server (air-gapped privacy).
     * "workflow_glue": Inter-ecosystem bridge syncing two tools/specs that do not natively communicate.
     * "opinionated_linter_scaffold": Policy enforcer or scaffold generator for a specific framework/protocol.
     * "specialized_cli": Focused, high-performance terminal utility for batch processing.

3. WORKAROUND MUTATION:
   - Each solution must directly replace the exact observed manual workaround mentioned in the evidence (e.g. bash scripts, manual regex, repetitive diffs).

4. INCUMBENT ASYMMETRY:
   - For each solution, state clearly why incumbents (e.g., Postman, GitHub, VS Code, Swagger) have a blind spot or will not solve this specific edge case.

Return a valid JSON object matching this schema:
{
  "cluster_id": (integer),
  "cluster_name": (string),
  "hypotheses": [
    {
      "opportunity_id": (string, e.g. "opp_cluster0_h1"),
      "cluster_id": (integer),
      "solution_name": (string, memorable product title),
      "archetype": (one of: "in_situ_devflow", "headless_middleware", "zero_data_client_wasm", "workflow_glue", "opinionated_linter_scaffold", "specialized_cli"),
      "target_segment": (string, narrow specific user segment),
      "triggering_context": (string, exact moment the developer needs this),
      "replaced_workaround": (string, specific manual coping mechanism being replaced),
      "core_mechanism": (string, 1-2 sentences on how it works under the hood),
      "why_incumbent_fails": (string, incumbent blindspot or friction),
      "key_assumptions": [string, list of assumptions],
      "search_queries": [string, 2-3 target search queries],
      "likely_failure_modes": [string, 1-2 major failure risks]
    }
  ]
}
"""


DEVELOPER_ARCHETYPES = {
    "in_situ_devflow", "headless_middleware", "zero_data_client_wasm",
    "workflow_glue", "opinionated_linter_scaffold", "specialized_cli",
}
GENERAL_ARCHETYPES = {
    "web_utility", "calculator", "browser_extension", "workflow_automation",
    "zero_data_client_wasm",
}
GENERAL_SYSTEM = """Generate 1 to 3 small tools for a general or non-developer professional audience.
Solve the exact job in the supplied evidence. A specific calculator, converter, checker,
generator, browser extension, or workflow automation can be sufficient. Use the supplied
workaround only if it was observed. Treat differentiation, search demand and revenue
as hypotheses. Return zero ideas if the evidence does not justify a useful tool.
Allowed archetypes: """ + ", ".join(sorted(GENERAL_ARCHETYPES)) + "\n" + HYPOTHESIZE_SYSTEM[
    HYPOTHESIZE_SYSTEM.index("Return a valid JSON object"):
].replace(
    'one of: "in_situ_devflow", "headless_middleware", "zero_data_client_wasm", "workflow_glue", "opinionated_linter_scaffold", "specialized_cli"',
    "one of the allowed archetypes above",
).replace("the developer needs", "the user needs")



def build_problem_context(cluster: dict, problems: list[dict]) -> ProblemContext:
    evidence_records: list[EvidenceRecord] = []
    for p in problems[:8]:
        quote = (p.get("evidence_quote") or "").replace("\n", " ").strip()
        if not quote:
            continue
        evidence_records.append(
            EvidenceRecord(
                doc_id=p.get("doc_id", "unknown"),
                quote=quote,
                user_type=p.get("user_type", "developer"),
                pain_level=int(p.get("pain_level", 3)),
                source=p.get("source") or p.get("doc_id", "").partition(":")[0],
                url=p.get("url", ""),
                author=p.get("author", ""),
                created_at=p.get("created_at", ""),
            )
        )

    return ProblemContext(
        cluster_id=cluster["id"],
        cluster_name=cluster.get("name", "Unnamed Cluster"),
        member_count=cluster.get("member_count", len(problems)),
        user_types=cluster.get("user_types", [])[:4],
        observed_workarounds=cluster.get("sample_workarounds", [])[:4],
        search_queries=cluster.get("search_queries", [])[:5],
        evidence_records=evidence_records,
    )


def generate_hypotheses_for_cluster(
    cluster: dict,
    problems: list[dict],
    client: OpenAI,
    force: bool = False,
    model: Optional[str] = None,
    track: ProductTrack | None = None,
) -> Optional[HypothesisSet]:
    cid = cluster["id"]
    context = build_problem_context(cluster, problems)
    target_model = model or IDEATE_MODEL
    system = GENERAL_SYSTEM if track == ProductTrack.GENERAL else HYPOTHESIZE_SYSTEM
    cache_key = json.dumps([track, target_model, system, cluster, problems], sort_keys=True)
    digest = hashlib.sha256(cache_key.encode("utf-8")).hexdigest()[:24]
    cache_file = HYPOTHESIS_CACHE_DIR / (
        f"{track.value}_{digest}.json" if track else f"cluster_{cid}.json"
    )
    if cache_file.exists() and not force:
        try:
            return HypothesisSet.model_validate_json(cache_file.read_text(encoding="utf-8"))
        except (OSError, ValidationError) as exc:
            log.warning("Cache parse failed for cluster %s: %s; regenerating...", cid, exc)

    evidence_bullets = "\n".join(
        f"- [{e.user_type} (Pain: {e.pain_level}/5)] \"{e.quote}\""
        for e in context.evidence_records
    )

    workarounds_text = (
        "\n".join(f"- {w}" for w in context.observed_workarounds)
        if context.observed_workarounds
        else "No workaround observed."
    )

    user_msg = f"""
Target Problem Cluster #{context.cluster_id}: {context.cluster_name}
Target Personas: {", ".join(context.user_types) or "Unknown"}
Observed Workarounds:
{workarounds_text}

Suggested Search Queries:
{", ".join(context.search_queries)}

Verbatim Evidence Statements:
{evidence_bullets}

Generate hypotheses for Cluster #{context.cluster_id} using the track instructions.
Return valid JSON only.
"""

    for attempt in range(3):
        try:
            resp = client.chat.completions.create(
                model=target_model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_msg},
                ],
                response_format={"type": "json_object"},
                temperature=0.4,
            )
            raw = resp.choices[0].message.content or "{}"
            parsed_json = json.loads(raw)
            # Ensure cluster fields match
            parsed_json["cluster_id"] = context.cluster_id
            parsed_json["cluster_name"] = context.cluster_name

            if track:
                for index, item in enumerate(parsed_json["hypotheses"], 1):
                    item.update(
                        cluster_id=cid, track=track,
                        evidence=[record.model_dump() for record in context.evidence_records],
                    )
                    item_digest = hashlib.sha256(json.dumps(item, sort_keys=True).encode()).hexdigest()[:24]
                    item["opportunity_id"] = f"opp_{track.value}_{digest}_{index}_{item_digest}"
                allowed = GENERAL_ARCHETYPES if track == ProductTrack.GENERAL else DEVELOPER_ARCHETYPES
                if any(h["archetype"] not in allowed for h in parsed_json["hypotheses"]):
                    raise ValueError(f"Hypothesis used an archetype outside the {track.value} track")
                parsed_json["track"] = track

            # Validate against Pydantic schema
            hypothesis_set = HypothesisSet.model_validate(parsed_json)

            # Check archetype diversity
            archetypes_used = {h.archetype for h in hypothesis_set.hypotheses}
            if track == ProductTrack.DEVELOPER and len(archetypes_used) < 3:
                raise ValueError("Developer track requires three distinct archetypes")
            if track is None and len(archetypes_used) < 2 and attempt < 2:
                log.warning(
                    "Cluster %s only produced %d unique archetype(s). Retrying for diversity...",
                    cid,
                    len(archetypes_used),
                )
                continue

            # Cache the valid result
            cache_file.write_text(
                json.dumps(hypothesis_set.model_dump(), indent=2),
                encoding="utf-8",
            )
            return hypothesis_set

        except ValidationError as val_err:
            log.warning("Validation error on cluster %s attempt %d: %s", cid, attempt, val_err)
        except Exception as exc:
            log.warning("LLM generation error on cluster %s attempt %d: %s", cid, attempt, exc)

    return None


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cluster-id", type=int, default=None, help="Specific cluster ID to hypothesize")
    ap.add_argument("--top-n", type=int, default=5, help="Number of clusters to process")
    ap.add_argument("--force", action="store_true", help="Force regeneration bypassing cache")
    args = ap.parse_args()

    if not CLUSTERS_PATH.exists() or not PROBLEMS_PATH.exists():
        print("Missing clusters.json or problems.jsonl. Ensure prior pipeline stages completed.")
        return

    clusters_data = json.loads(CLUSTERS_PATH.read_text(encoding="utf-8"))
    clusters = clusters_data.get("clusters", [])

    problems_by_id = {}
    for line in PROBLEMS_PATH.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                p = json.loads(line)
                problems_by_id[p["doc_id"]] = p
            except Exception:
                pass

    client_kwargs = {"api_key": LLM_API_KEY, "timeout": LLM_TIMEOUT}
    if LLM_BASE_URL:
        client_kwargs["base_url"] = LLM_BASE_URL
    client = OpenAI(**client_kwargs)

    targets = [c for c in clusters if c["id"] == args.cluster_id] if args.cluster_id is not None else clusters[: args.top_n]

    print(f"\n=== Generating Diverse Solution Hypotheses for {len(targets)} Clusters ===\n")
    for cluster in targets:
        cid = cluster["id"]
        member_probs = [problems_by_id[m] for m in cluster.get("members", []) if m in problems_by_id]
        print(f"Processing Cluster #{cid}: {cluster['name']} ({len(member_probs)} evidence items)...")
        res = generate_hypotheses_for_cluster(cluster, member_probs, client, force=args.force)
        if res:
            archetypes = [h.archetype.value for h in res.hypotheses]
            print(f"  -> Generated {len(res.hypotheses)} hypotheses across archetypes: {archetypes}")
            for idx, h in enumerate(res.hypotheses, 1):
                print(f"     {idx}. [{h.archetype.value}] {h.solution_name}: {h.core_mechanism[:90]}...")
        else:
            print(f"  -> FAILED to generate hypotheses for Cluster #{cid}")
        print()


if __name__ == "__main__":
    main()
