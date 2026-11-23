from scrapling.fetchers import Fetcher, StealthyFetcher
import json

urls = [
    "https://www.reddit.com/r/productivity/comments/r75slk/is_there_a_tool_for_this/",
    "https://www.quora.com/Are-there-apps-you-can-download-that-trace-or-track-anyone-that-has-or-may-be-using-your-personal-information-on-their-personal-devices-by-their-location"
]

for url in urls:
    print("--- URL:", url)
    try:
        page = Fetcher.get(url)
        print("Fetcher.get status:", page.status, "text len:", len(page.get_all_text()))
        text = page.get_all_text()
        if len(text) > 100:
            print("Snippet:", text[:300].strip())
        else:
            # Let's inspect html
            html = page.html_content.decode("utf-8", "ignore") if isinstance(page.html_content, bytes) else str(page.html_content)
            print("HTML len:", len(html))
            # Check title
            import re
            m = re.search(r'<title>(.*?)</title>', html, re.I)
            if m:
                print("Title:", m.group(1))
    except Exception as e:
        print("Fetcher error:", e)
