import html
import json
import re
from pathlib import Path

import feedparser


RSS_FEEDS = [
    {
        "publisher": "조선일보",
        "category": "정치",
        "url": "https://www.chosun.com/arc/outboundfeeds/rss/category/politics/?outputType=xml",
    },
    {
        "publisher": "조선일보",
        "category": "경제",
        "url": "https://www.chosun.com/arc/outboundfeeds/rss/category/economy/?outputType=xml",
    },
    {
        "publisher": "조선일보",
        "category": "사회",
        "url": "https://www.chosun.com/arc/outboundfeeds/rss/category/national/?outputType=xml",
    },
    {
        "publisher": "한겨레",
        "category": "정치",
        "url": "https://www.hani.co.kr/rss/politics/",
    },
    {
        "publisher": "한겨레",
        "category": "경제",
        "url": "https://www.hani.co.kr/rss/economy/",
    },
    {
        "publisher": "한겨레",
        "category": "사회",
        "url": "https://www.hani.co.kr/rss/society/",
    },
]

# 언론사·카테고리(RSS)별로 수집할 최대 기사 수
ARTICLE_LIMIT_PER_FEED = 20


def clean_html_text(text):
    """
    RSS 설명에 포함된 HTML 태그와 불필요한 공백을 제거한다.
    """
    if not text:
        return ""

    text = html.unescape(text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)

    return text.strip()


def collect_articles():
    news_items = []

    # 언론사·카테고리별 수집 개수를 관리
    feed_counts = {}

    for feed_info in RSS_FEEDS:
        publisher = feed_info["publisher"]
        category = feed_info["category"]
        feed_url = feed_info["url"]

        # 예: ("조선일보", "정치")
        feed_key = (publisher, category)
        feed_counts[feed_key] = 0

        print(f"\n{publisher} - {category} RSS 수집 중...")
        feed = feedparser.parse(feed_url)

        if feed.bozo:
            print(
                f"{publisher} {category} RSS 파싱 경고: "
                f"{feed.bozo_exception}"
            )

        for entry in feed.entries:
            # 해당 언론사·카테고리에서 20개를 채우면 중단
            if feed_counts[feed_key] >= ARTICLE_LIMIT_PER_FEED:
                break

            title = clean_html_text(entry.get("title", ""))

            description = clean_html_text(
                entry.get("summary")
                or entry.get("description")
                or ""
            )

            link = entry.get("link", "")

            published = (
                entry.get("published")
                or entry.get("updated")
                or ""
            )

            if not title or not link:
                continue

            # 같은 링크의 기사가 이미 들어갔다면 제외
            if any(item["link"] == link for item in news_items):
                continue

            news_items.append(
                {
                    "publisher": publisher,
                    "category": category,
                    "title": title,
                    "link": link,
                    "published": published,
                    "description": description,
                }
            )

            feed_counts[feed_key] += 1

            print(
                f"[{feed_counts[feed_key]}/"
                f"{ARTICLE_LIMIT_PER_FEED}] "
                f"{title}"
            )

    print("\n카테고리별 수집 결과")

    for (publisher, category), count in feed_counts.items():
        print(f"{publisher} - {category}: 총 {count}개 수집 완료")

    return news_items


def save_articles(news_items):
    output_path = Path("data/news.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("w", encoding="utf-8") as file:
        json.dump(
            news_items,
            file,
            ensure_ascii=False,
            indent=2,
        )

    print(f"\n총 {len(news_items)}개 기사를 {output_path}에 저장했습니다.")
    print("이 단계에서는 Solar API를 사용하지 않습니다.")


def main():
    news_items = collect_articles()
    save_articles(news_items)


if __name__ == "__main__":
    main()