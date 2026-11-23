"""Eyeball the collected evidence before spending LLM money on it.

  python -m src.inspect_raw --n 10
"""
from __future__ import annotations

import argparse
import sys

import pandas as pd

from .config import RAW_PATH

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=10)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()

    df = pd.read_json(RAW_PATH, lines=True)
    print(f"{len(df)} docs\n")
    print(df.groupby(["source", "kind"]).size().to_string(), "\n")
    print("Text length:\n", df["text"].str.len().describe().round(0).to_string(), "\n")
    print("Top communities:\n", df["community"].value_counts().head(10).to_string(), "\n")
    print("Docs per keyword:\n", df["keyword"].value_counts().to_string(), "\n")
    print("Highest demand signal (score):")
    for _, r in df.sort_values("score", ascending=False).head(5).iterrows():
        print(f"  [{r.score}] {r.title[:90]}  {r.url}")

    print(f"\n--- {args.n} random docs: read these by hand ---")
    for _, r in df.sample(min(args.n, len(df)), random_state=args.seed).iterrows():
        print(f"\n[{r.source}/{r.kind}] {r.url}\n{r.text[:350].replace(chr(10), ' ')}")


if __name__ == "__main__":
    main()
