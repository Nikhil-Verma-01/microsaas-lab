import json
from src.config import PROBLEMS_PATH

probs = [json.loads(line) for line in PROBLEMS_PATH.open(encoding='utf-8') if line.strip()]
web_probs = [p for p in probs if p.get('doc_id', '').startswith('web:')]
print(f"Total web problems extracted: {len(web_probs)}\n")

for i, p in enumerate(web_probs, 1):
    print(f"[{i}] Target User: {p.get('user_type')} | Pain Level: {p.get('pain_level')}/5")
    print(f"    Problem: {p.get('problem')}")
    print(f"    Automation: {p.get('potential_automation')}")
    print(f"    Likely Search Query: {p.get('likely_search_query')}")
    print(f"    Workaround: {p.get('current_workaround')}")
    print("-" * 75)
