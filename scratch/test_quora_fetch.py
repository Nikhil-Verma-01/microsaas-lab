from scrapling.fetchers import Fetcher, StealthyFetcher
from ddgs import DDGS

with DDGS() as ddgs:
    hits = list(ddgs.text("site:quora.com is there an online tool to", max_results=5))

for h in hits:
    print("Quora Hit:", h["title"], h["href"])
    try:
        page = Fetcher.get(h["href"])
        print("  Status:", page.status, "Text len:", len(page.get_all_text()))
        if len(page.get_all_text()) > 200:
            print("  Snippet:", page.get_all_text()[:250].strip())
    except Exception as e:
        print("  Error:", e)
