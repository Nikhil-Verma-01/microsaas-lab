from scrapling.fetchers import Fetcher
from urllib.parse import quote_plus

query = '"is there a tool for" site:reddit.com'
url = f"https://search.yahoo.com/search?p={quote_plus(query)}"

page = Fetcher.get(url)
print("Status:", page.status)
# Let's inspect all h3 and a elements
h3s = [h.get_all_text().strip() for h in page.css("h3")]
print("H3 count:", len(h3s))
print("Sample H3s:", h3s[:5])

# Find links with reddit.com
reddit_links = []
for a in page.css("a"):
    h = a.attrib.get("href", "")
    t = a.get_all_text().strip()
    if "reddit.com" in h or "reddit.com" in t:
        reddit_links.append((t, h))
print(f"Reddit links found: {len(reddit_links)}")
for t, h in reddit_links[:5]:
    print(" ", t, "->", h[:60])
