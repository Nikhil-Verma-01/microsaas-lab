from scrapling.fetchers import Fetcher
import re

url = "https://www.reddit.com/r/Entrepreneur/comments/18j1zdf/is_there_a_tool_for_this/"
page = Fetcher.get(url)

print("Title:", page.css("title::text"))
print("Meta og:title:", [e.attrib.get("content") for e in page.css("meta[property='og:title']")])
print("Meta og:description:", [e.attrib.get("content") for e in page.css("meta[property='og:description']")])
print("Meta twitter:description:", [e.attrib.get("content") for e in page.css("meta[name='twitter:description']")])
print("All h1:", [e.get_all_text() for e in page.css("h1")])
print("All p:", [e.get_all_text() for e in page.css("p")][:10])

# Check for JSON in script tags
for s in page.css("script"):
    txt = s.get_all_text()
    if "is there a tool" in txt.lower():
        print("Found script containing target phrase! snippet:", txt[:200])
