from scrapling.fetchers import Fetcher
from urllib.parse import quote_plus, unquote
import re

query = '"is there a tool for" site:reddit.com'
url = f"https://search.yahoo.com/search?p={quote_plus(query)}"
page = Fetcher.get(url)

for li in page.css("ol.searchCenterMiddle li, div.compText, div#web li"):
    h3 = li.css("h3")
    if not h3:
        continue
    title = h3[0].get_all_text().strip()
    a = li.css("a")
    if a:
        href = a[0].attrib.get("href", "")
        # Extract target url if redirected
        m = re.search(r'/RU=([^/]+)/', href)
        real_url = unquote(m.group(1)) if m else href
        print(f"Title: {title}\n  URL: {real_url}\n")
