from ddgs import DDGS

d = DDGS()
query = 'is there an online tool for'

for engine in ['duckduckgo', 'yahoo', 'brave', 'mojeek']:
    try:
        res = d.text(query, backend=engine, max_results=3)
        print(f"Engine {engine}: {len(res)} results")
        for r in res[:2]:
            print(f"   [{r.get('title')}] -> {r.get('href')}")
    except Exception as e:
        print(f"Engine {engine} failed: {type(e).__name__}: {e}")
