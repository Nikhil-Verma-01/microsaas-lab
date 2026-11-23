from ddgs import DDGS
from scrapling.fetchers import Fetcher

with DDGS() as ddgs:
    hits = list(ddgs.text("is there an app or tool to site:quora.com", max_results=5))

print(f"Found {len(hits)} hits:")
for h in hits:
    print("URL:", h["href"])
    print("Title:", h["title"])
    print("Snippet:", h["body"])
    print()
