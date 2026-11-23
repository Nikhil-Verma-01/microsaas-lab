from scrapling.fetchers import Fetcher
from urllib.parse import quote_plus, unquote
import re

queries = [
    '"is there a tool for" site:quora.com',
    '"is there an app for" site:quora.com',
    '"is there a website that" site:quora.com',
    '"is there a free tool" site:quora.com',
]

for q in queries:
    url = f"https://search.yahoo.com/search?p={quote_plus(q)}"
    page = Fetcher.get(url)
    print(f"\n--- Query: {q} (Status {page.status}) ---")
    for li in page.css("ol.searchCenterMiddle li, div#web li"):
        h3 = li.css("h3")
        if not h3:
            continue
        title = h3[0].get_all_text().strip()
        a = li.css("a")
        if a:
            href = a[0].attrib.get("href", "")
            m = re.search(r'/RU=([^/]+)/', href)
            real_url = unquote(m.group(1)) if m else href
            if "quora.com" in real_url:
                print(f"Title: {title}\n  URL: {real_url}")
