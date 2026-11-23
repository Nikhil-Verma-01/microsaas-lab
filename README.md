# microsaas-lab

One-week experiment: can an evidence -> problem -> cluster -> score pipeline surface
micro-SaaS ideas you would actually build? Collection stage only (Day 2); later
stages (extract, cluster, score) get added to `src/` as separate modules.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                    # add GITHUB_TOKEN
```

GitHub token: Settings -> Developer settings -> Personal access tokens. No scopes
are needed for public search. Without it you are limited to ~10 searches/min.

## Run

```bash
# 1. See the query plan first (no network calls)
python -m src.collect --keywords csv excel reconcile --dry-run

# 2. Small pilot: ~50 docs. Read every one.
python -m src.collect --keywords csv --sources github hn \
    --per-query 20 --max-phrases 4 --limit-per-source 25
python -m src.inspect_raw --n 15

# 3. Scale up only when the pilot looks relevant
python -m src.collect --keywords csv excel reconcile "data diff" \
    --per-query 50 --max-phrases 8 --since 2023-01-01 --limit-per-source 400

# Optional: bias GitHub toward feature requests (usually better than bug reports)
python -m src.collect --keywords openapi --sources github --gh-extra "label:enhancement"
```

Output: `data/raw.jsonl`, one JSON document per line, deduplicated by `id` across runs.
Each record keeps `url`, `score` (reactions/points), `comments`, `community`, and the
exact `query` that found it, so every later claim can link back to evidence.

## Competitor check (Day 5)

Uses Scrapling. Install the extra: `pip install "scrapling[fetchers]"` (already in requirements.txt).
Plain `Fetcher` needs no browser. Only the Dynamic/Stealthy fetchers need `scrapling install`.

```bash
python -m src.web_fetch https://some-competitor.com/tool
```

Checks robots.txt first, then reports word count, latest copyright year, enterprise
markers ("contact sales"), free-tier markers, and visible prices.

## Notes

- Pick ONE niche (3-5 keywords). Thin evidence across many niches is the usual failure.
- GitHub issues are mostly bug reports. If the pilot looks like bugs, use `--gh-extra "label:enhancement"`.
- GitHub search returns max 1,000 results per query: use more specific queries, not bigger limits.
- Scraped text is research input only. Anything you publish must be your own original work.

## Discover ideas for a product track

Use Python 3.10 or newer. Install the requirements and configure your model provider in `.env`. These commands process the saved corpus and write a fresh report for each track.

```bash
python -m src.discover --track developer --limit 50 --top-n 3
python -m src.discover --track general --limit 30 --top-n 3
```

The developer track uses saved GitHub and Hacker News documents by default. The general track uses the other sources in the saved corpus. For either track, pass `--raw path/to/documents.jsonl` to use a curated source set in the existing document format. Include a stable ID, URL, source, author, title, and actual discussion text for each document. Use approved sources and access methods. The general report command, `python -m src.generate_general_report`, uses the same pipeline and defaults to the general track.

Each run writes `problems.jsonl`, `clusters.json`, `report.md`, and `scores.csv` under `data/discovery/developer/` or `data/discovery/general/`. A run can legitimately surface zero ideas. Clusters with fewer than two independent authors and URLs are retained as leads in `clusters.json`. Use `--model` to compare generation models on the same extracted evidence. Extraction and hypotheses are cached by inputs and model. Candidate evaluation refreshes on each run.

Candidates stay on hold until reviewed demand evidence is available. Pass `--market-evidence path/to/reviewed.json` with entries keyed by the opportunity IDs in the report. Each entry needs `basis`, `url`, and `observation`. Use `paid_demand` for evidence about spend or willingness to pay for the specific workflow. For general utilities, `search_demand` also qualifies when it documents demand for the exact task. Include the observed result in the entry. Candidate IDs are stable across cached runs and change when the underlying hypothesis changes.

Earlier reports under `data/` are historical snapshots. Use the track-specific outputs for new discovery runs.
