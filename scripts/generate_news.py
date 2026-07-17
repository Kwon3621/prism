import hashlib
import html
import json
import re
from pathlib import Path

import feedparser

import requests

from datetime import datetime, timezone


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
        {
        "publisher": "한국경제",
        "category": "정치",
        "url": "https://www.hankyung.com/feed/politics",
    },
    {
        "publisher": "한국경제",
        "category": "경제",
        "url": "https://www.hankyung.com/feed/economy",
    },
    {
        "publisher": "한국경제",
        "category": "사회",
        "url": "https://www.hankyung.com/feed/society",
    },
        {
        "publisher": "동아일보",
        "category": "정치",
        "url": "https://rss.donga.com/politics.xml",
    },
    {
        "publisher": "동아일보",
        "category": "경제",
        "url": "https://rss.donga.com/economy.xml",
    },
    {
        "publisher": "동아일보",
        "category": "사회",
        "url": "https://rss.donga.com/national.xml",
    },
    {
        "publisher": "매일경제",
        "category": "정치",
        "url": "https://www.mk.co.kr/rss/30200030/",
    },
    {
        "publisher": "매일경제",
        "category": "경제",
        "url": "https://www.mk.co.kr/rss/30100041/",
    },
    {
        "publisher": "매일경제",
        "category": "사회",
        "url": "https://www.mk.co.kr/rss/50400012/",
    },
    {
        "publisher": "SBS",
        "category": "정치",
        "url": "https://news.sbs.co.kr/news/SectionRssFeed.do?sectionId=01&plink=RSSREADER",
    },
    {
        "publisher": "SBS",
        "category": "경제",
        "url": "https://news.sbs.co.kr/news/SectionRssFeed.do?sectionId=02&plink=RSSREADER",
    },
    {
        "publisher": "SBS",
        "category": "사회",
        "url": "https://news.sbs.co.kr/news/SectionRssFeed.do?sectionId=03&plink=RSSREADER",
    },
]

PUBLISHER_IDS = {
    "조선일보": "chosun",
    "한겨레": "hani",
    "한국경제": "hankyung",
    "동아일보": "donga",
    "매일경제": "mk",
    "SBS": "sbs",
}

# 언론사·카테고리(RSS)별로 수집할 최대 기사 수
ARTICLE_LIMIT_PER_FEED = 40


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
def normalize_url(url):
    """
    기사 URL의 불필요한 공백과 끝 슬래시를 정리한다.
    """
    if not url:
        return ""

    return url.strip().rstrip("/")


def create_article_id(publisher, link):
    """
    동일한 기사 URL은 실행할 때마다 같은 article_id를 갖는다.
    """
    normalized_link = normalize_url(link)

    raw_id = f"{publisher}|{normalized_link}"

    hashed_id = hashlib.sha256(
        raw_id.encode("utf-8")
    ).hexdigest()[:16]

    return f"article-{hashed_id}"


def get_published_at(entry):
    """
    RSS 항목의 발행 시각을 ISO 8601 형식으로 반환한다.
    발행 시각을 확인할 수 없으면 빈 문자열을 반환한다.
    """
    parsed_time = (
        entry.get("published_parsed")
        or entry.get("updated_parsed")
    )

    if parsed_time:
        published_datetime = datetime(
            parsed_time.tm_year,
            parsed_time.tm_mon,
            parsed_time.tm_mday,
            parsed_time.tm_hour,
            parsed_time.tm_min,
            parsed_time.tm_sec,
            tzinfo=timezone.utc,
        )

        return published_datetime.isoformat()

    published_text = (
        entry.get("published")
        or entry.get("updated")
        or ""
    )

    return published_text.strip()


def sanitize_rss_xml(xml_text):
    """
    XML에서 기본적으로 허용되지 않는 HTML 이름 엔티티를
    실제 문자로 변환한다.

    XML 기본 엔티티인 amp, lt, gt, quot, apos는 그대로 유지한다.
    """
    xml_entities = {"amp", "lt", "gt", "quot", "apos"}

    def replace_entity(match):
        entity_name = match.group(1)
        original_entity = match.group(0)

        if entity_name in xml_entities:
            return original_entity

        decoded_entity = html.unescape(original_entity)

        # Python이 인식하는 HTML 엔티티라면 실제 문자로 변환
        if decoded_entity != original_entity:
            return decoded_entity

        # 알 수 없는 엔티티는 일반 문자열로 처리
        return f"&amp;{entity_name};"

    return re.sub(
        r"&([A-Za-z][A-Za-z0-9]+);",
        replace_entity,
        xml_text,
    )

def parse_rss_feed(feed_url):
    """
    RSS 원문을 직접 요청한 뒤 XML 엔티티를 정리해서 파싱한다.
    """
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 Chrome/150.0.0.0 Safari/537.36"
        )
    }

    response = requests.get(
        feed_url,
        headers=headers,
        timeout=20,
    )
    response.raise_for_status()

    # 서버가 제공한 인코딩을 우선 사용하고,
    # 없으면 requests가 추정한 인코딩을 사용
    if not response.encoding:
        response.encoding = response.apparent_encoding

    cleaned_xml = sanitize_rss_xml(response.text)

    return feedparser.parse(cleaned_xml)

def collect_articles():
    news_items = []

    collected_at = datetime.now(
        timezone.utc
    ).isoformat()

    # 언론사·카테고리별 수집 개수를 관리
    feed_counts = {}

    for feed_info in RSS_FEEDS:
        publisher = feed_info["publisher"]
        publisher_id = PUBLISHER_IDS[publisher]
        category = feed_info["category"]
        feed_url = feed_info["url"]

        # 예: ("조선일보", "정치")
        feed_key = (publisher, category)
        feed_counts[feed_key] = 0

        print(f"\n{publisher} - {category} RSS 수집 중...")
        try:
            feed = parse_rss_feed(feed_url)
        except requests.RequestException as error:
            print(
                f"{publisher} {category} RSS 요청 실패: "
                f"{error}"
            )
            continue

        if feed.bozo:
            print(
                f"{publisher} {category} RSS 파싱 경고: "
                f"{feed.bozo_exception}"
            )

        for entry in feed.entries:
            # 해당 언론사·카테고리에서 최대 수량을 채우면 중단
            if feed_counts[feed_key] >= ARTICLE_LIMIT_PER_FEED:
                break

            title = clean_html_text(entry.get("title", ""))

            description = clean_html_text(
                entry.get("summary")
                or entry.get("description")
                or ""
            )

            link = normalize_url(
                entry.get("link", "")
            )

            published_at = get_published_at(entry)

            if not title or not link:
                continue

            # 같은 링크의 기사가 이미 들어갔다면 제외
            if any(item["link"] == link for item in news_items):
                continue

            article_id = create_article_id(
                publisher=publisher,
                link=link
            )

            embedding_text = " ".join(
                text
                for text in [title, description]
                if text
            ).strip()

            news_items.append(
                {
                    "article_id": article_id,
                    "publisher_id": publisher_id,
                    "publisher": publisher,
                    "category": category,
                    "title": title,
                    "link": link,
                    "published": published_at,
                    "published_at": published_at,
                    "collected_at": collected_at,
                    "updated_at": collected_at,
                    "description": description,
                    "embedding_text": embedding_text,
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