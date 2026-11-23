from scrapling.fetchers import Fetcher
from urllib.parse import quote_plus, unquote
import re

queries = [
    '"is there a tool" site:community.spiceworks.com',
    '"is there a tool for" site:superuser.com',
    '"is there a tool to" site:answers.microsoft.com',
]

for q in queries:
    url = f"https://search.yahoo.com/search?p={quote_plus(q)}"
    page = Fetcher.get(url)
    print(f"\nQuery: {q}")
    for li in page.css("ol.searchCenterMiddle li, div#web li")[:3]:
        h3 = li.css("h3")
        a = li.css("a")
        if h3 and a:
            title = h3[0].get_all_text().strip()
            href = a[0].attrib.get("href", "")
            m = re.search(r'/RU=([^/]+)/', href)
            real_url = unquote(m.group(1)) if m else href
            print(f"  Hit: {title} -> {real_url}")
