from scrapling.fetchers import Fetcher
import re

url = "https://www.reddit.com/r/Entrepreneur/comments/18j1zdf/is_there_a_tool_for_this/"
page = Fetcher.get(url)
html = page.html_content.decode("utf-8", "ignore") if isinstance(page.html_content, bytes) else str(page.html_content)

print("HTML size:", len(html))

# Check for shreddit-post attributes
post_m = re.search(r'<shreddit-post\s+([^>]+)>', html)
if post_m:
    attrs = post_m.group(1)
    for attr in ["post-title", "author", "score", "comment-count"]:
        m = re.search(rf'{attr}="([^"]*)"', attrs)
        if m:
            print(f"shreddit-post {attr}:", m.group(1))

# Check for text in slot="text-body"
body_m = re.search(r'<div[^>]*slot="text-body"[^>]*>(.*?)</div>', html, re.DOTALL)
if body_m:
    print("Found text-body:", body_m.group(1)[:300])

# Check for comments
comments = re.findall(r'<shreddit-comment\s+([^>]+)>', html)
print(f"Found {len(comments)} comments in shreddit-comment tags!")
