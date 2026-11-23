from scrapling.fetchers import Fetcher
from urllib.parse import quote_plus
import re

query = '"is there a tool for" site:reddit.com'
url = f"https://search.yahoo.com/search?p={quote_plus(query)}"

print("Fetching Yahoo with Scrapling Fetcher...")
page = Fetcher.get(url)
print("Status:", page.status)

# Extract search result links
results = []
for a in page.css("div#web ol li div.compText h3 a, div#web ol li h3.title a"):
    href = a.attrib.get("href")
    title = a.get_all_text().strip()
    if href and "r.search.yahoo.com" in href:
        results.append((title, href))

print(f"Found {len(results)} results from Yahoo with Scrapling:")
for t, h in results[:5]:
    print(" ", t)
