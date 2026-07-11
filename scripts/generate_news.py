import json
import os
from pathlib import Path

import feedparser
from dotenv import load_dotenv
from openai import OpenAI


RSS_FEEDS = [
    {
        "publisher": "조선일보",
        "url": "https://www.chosun.com/arc/outboundfeeds/rss/?outputType=xml",
    },
    {
        "publisher": "한겨레",
        "url": "https://www.hani.co.kr/rss/",
    },
]

ARTICLE_LIMIT_PER_PUBLISHER = 5


load_dotenv()

api_key = os.getenv("UPSTAGE_API_KEY")

if not api_key:
    raise ValueError("UPSTAGE_API_KEY를 찾을 수 없습니다.")

client = OpenAI(
    api_key=api_key,
    base_url="https://api.upstage.ai/v1",
)


def summarize_article(title, description):
    prompt = f"""
다음 뉴스 정보를 바탕으로 핵심 내용을 한국어 2문장으로 요약하세요.

규칙:
- 제공된 정보에 없는 사실은 추가하지 마세요.
- 기자나 언론사의 의도를 추정하지 마세요.
- 과장하거나 평가하지 마세요.
- 독자가 빠르게 이해할 수 있도록 간결하게 작성하세요.

제목: {title}
설명: {description}
"""

    response = client.chat.completions.create(
        model="solar-pro3",
        messages=[
            {
                "role": "user",
                "content": prompt,
            }
        ],
    )

    return response.choices[0].message.content.strip()


news_items = []

for feed_info in RSS_FEEDS:
    publisher = feed_info["publisher"]
    feed = feedparser.parse(feed_info["url"])

    for entry in feed.entries[:ARTICLE_LIMIT_PER_PUBLISHER]:
        title = entry.get("title", "제목 없음")
        description = entry.get("summary", "설명 없음")

        print(f"요약 중: {title}")

        try:
            summary = summarize_article(title, description)
        except Exception as error:
            print(f"요약 실패: {error}")
            summary = "요약을 생성하지 못했습니다."

        news_items.append(
            {
                "publisher": publisher,
                "title": title,
                "link": entry.get("link", "링크 없음"),
                "published": entry.get("published", "발행 시각 없음"),
                "description": description,
                "summary": summary,
            }
        )

output_path = Path("data/news.json")
output_path.parent.mkdir(exist_ok=True)

with output_path.open("w", encoding="utf-8") as file:
    json.dump(news_items, file, ensure_ascii=False, indent=2)

print(f"{len(news_items)}개 기사를 Solar로 요약해 {output_path}에 저장했습니다.")