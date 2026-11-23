from scrapling.fetchers import Fetcher
from ddgs import DDGS

print("--- Testing Quora ---")
with DDGS() as ddgs:
    q_hits = list(ddgs.text('"is there a tool for" site:quora.com', max_results=3))
for h in q_hits:
    print("Hit:", h["title"], h["href"])
    try:
        p = Fetcher.get(h["href"])
        print("Status:", p.status, "Title:", p.css("title::text"))
        text = p.get_all_text()
        print("Text len:", len(text), "Snippet:", text[:200].strip())
    except Exception as e:
        print("Error:", e)
