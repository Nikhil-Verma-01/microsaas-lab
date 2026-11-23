from scrapling.fetchers import Fetcher
import re

url = "https://www.reddit.com/r/productivity/comments/r75slk/is_there_a_tool_for_this/"
page = Fetcher.get(url)

# Let's inspect all shreddit-post or post container
for el in page.css("shreddit-post, div[data-testid='post-container']"):
    print("Post tag:", el.tag)
    print("Post attrs:", {k: v for k, v in el.attrib.items() if k in ['post-title', 'author', 'score', 'comment-count', 'subreddit-prefixed-name']})

# Check where the main text is
body_elements = page.css("div[slot='text-body'], div.text-neutral-content, div[data-click-id='text']")
print("Body elements found:", len(body_elements))
for b in body_elements:
    print("Body text:\n", b.get_all_text().strip())

# Check comments
comments = page.css("shreddit-comment")
print(f"shreddit-comment count: {len(comments)}")
for c in comments[:3]:
    print("Comment author:", c.attrib.get("author"))
    print("Comment text:", c.get_all_text().strip()[:150])
