from scrapling.fetchers import Fetcher
import re

url = "https://www.reddit.com/r/productivity/comments/r75slk/is_there_a_tool_for_this/"
page = Fetcher.get(url)

# Search for comments or responses in html
html = page.html_content.decode("utf-8", "ignore") if isinstance(page.html_content, bytes) else str(page.html_content)
print("Comment tags or texts:")
for m in re.finditer(r'<p[^>]*class="[^"]*comment[^"]*"[^>]*>(.*?)</p>', html, re.I):
    print("Found comment:", m.group(1)[:100])

# Check for slot="comment"
for c in page.css("div[slot='comment'], div[data-testid='comment']"):
    print("Comment:", c.get_all_text().strip()[:100])
