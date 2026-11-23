from scrapling.fetchers import Fetcher
import re

urls = [
    "https://www.reddit.com/r/Entrepreneur/comments/1cmy9c7/is_there_a_tool_for_this/",
    "https://www.reddit.com/r/productivity/comments/r75slk/is_there_a_tool_for_this/",
    "https://www.reddit.com/r/VideoEditing/comments/15k14gm/is_there_a_tool_that_does_this/",
    "https://www.reddit.com/r/learntodraw/comments/1dbh413/is_there_a_tool_for_this/"
]

for url in urls:
    page = Fetcher.get(url)
    text = page.get_all_text()
    print("=" * 60)
    print("URL:", url)
    print("Status:", page.status, "Length:", len(text))
    # Look for the user content
    # In Reddit, the post text is usually between author/time and "Read more" / "Share" / "Top Posts"
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    # Print interesting lines
    print("Extracted post text sample:")
    for line in lines[10:25]:
        if not any(stop in line for stop in ["Sign Up", "Log in", "Reddit Rules", "Privacy Policy", "By continuing"]):
            print("  ", line)
