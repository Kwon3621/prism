import json
from pathlib import Path

import feedparser


RSS_URL = "https://www.chosun.com/arc/outboundfeeds/rss/?outputType=xml"

feed = feedparser.parse(RSS_URL)

news_items = []

for entry in feed.entries[:5]:
    news_items.append(
        {
            "publisher": "조선일보",
            "title": entry.get("title", "제목 없음"),
            "link": entry.get("link", "링크 없음"),
        }
    )

output_path = Path("data/news.json")
output_path.parent.mkdir(exist_ok=True)

with output_path.open("w", encoding="utf-8") as file:
    json.dump(news_items, file, ensure_ascii=False, indent=2)

print(f"{len(news_items)}개 기사를 {output_path}에 저장했습니다.")