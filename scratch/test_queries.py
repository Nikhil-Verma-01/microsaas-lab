from ddgs import DDGS

queries = [
    'is there a tool for site:quora.com',
    'is there a tool to site:reddit.com',
    'looking for a tool that site:reddit.com',
    'is there an app that can site:quora.com',
    'any tool that can site:reddit.com',
]

with DDGS() as ddgs:
    for q in queries:
        try:
            hits = list(ddgs.text(q, max_results=3))
            print(f"Query '{q}': found {len(hits)} hits")
            for h in hits[:2]:
                print(f"  - [{h['title']}] -> {h['href']}")
        except Exception as e:
            print(f"Query '{q}': Error {e}")
