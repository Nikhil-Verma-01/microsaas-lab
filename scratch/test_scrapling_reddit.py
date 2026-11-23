from scrapling.fetchers import Fetcher

url = "https://www.reddit.com/r/Entrepreneur/comments/18j1zdf/is_there_a_tool_for_this/"
page = Fetcher.get(url)
print("Status:", page.status)
md = page.markdown()
print("Markdown length:", len(md))
print("Markdown snippet:\n", md[:500])
