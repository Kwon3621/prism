import html
import json
import re
import hashlib
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import feedparser

import requests

from email.utils import format_datetime
from datetime import datetime, timedelta, timezone


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

# 언론사·카테고리(RSS)별로 수집할 최대 기사 수, 최신 기사 우선 반영,저장소 최대 저장 날짜
ARTICLE_LIMIT_PER_FEED = 40
PRIORITY_WINDOW_HOURS = 24
RETENTION_DAYS = 30
PUBLISHER_IDS = {
    "조선일보": "chosun",
    "한겨레": "hani",
    "한국경제": "hankyung",
    "동아일보": "donga",
    "매일경제": "mk",
    "SBS": "sbs",
}

def normalize_link(link):
    parts = urlsplit(link.strip())

    tracking_params = {
        "plink",
        "cooper",
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_term",
        "utm_content",
    }

    filtered_query = [
        (key, value)
        for key, value in parse_qsl(
            parts.query,
            keep_blank_values=True,
        )
        if key.lower() not in tracking_params
    ]

    return urlunsplit(
        (
            parts.scheme,
            parts.netloc,
            parts.path,
            urlencode(filtered_query),
            "",
        )
    )


def create_article_id(link):
    normalized_link = normalize_link(link)

    return hashlib.sha256(
        normalized_link.encode("utf-8")
    ).hexdigest()

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

def get_entry_datetime(entry):
    """
    RSS 항목의 발행 시각을 UTC datetime으로 변환한다.
    발행 시각을 확인할 수 없으면 None을 반환한다.
    """
    parsed_time = (
        entry.get("published_parsed")
        or entry.get("updated_parsed")
    )

    if not parsed_time:
        return None

    return datetime(
        parsed_time.tm_year,
        parsed_time.tm_mon,
        parsed_time.tm_mday,
        parsed_time.tm_hour,
        parsed_time.tm_min,
        parsed_time.tm_sec,
        tzinfo=timezone.utc,
    )

def parse_published_datetime(published):
    """
    저장된 기사 발행 시각 문자열을 UTC datetime으로 변환한다.
    변환할 수 없으면 None을 반환한다.
    """
    if not published:
        return None

    try:
        parsed = datetime.fromisoformat(
            published.replace("Z", "+00:00")
        )

        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)

        return parsed.astimezone(timezone.utc)

    except ValueError:
        try:
            from email.utils import parsedate_to_datetime

            parsed = parsedate_to_datetime(published)

            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)

            return parsed.astimezone(timezone.utc)

        except (TypeError, ValueError):
            return None

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

        try:
            feed = parse_rss_feed(feed_url)
            print(f"RSS에서 제공된 항목 수: {len(feed.entries)}개")
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

        recent_entries = []
        older_entries = []

        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(hours=PRIORITY_WINDOW_HOURS)

        for entry in feed.entries:
            published_dt = get_entry_datetime(entry)

            if published_dt and published_dt >= cutoff:
                recent_entries.append(entry)
            else:
                older_entries.append(entry)

        candidate_entries = recent_entries + older_entries
        

        for entry in candidate_entries:
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


            if not published:
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
                        tzinfo=timezone.utc
                    )

                    published = format_datetime(published_datetime)

            if not title or not link:
                continue

            article_id = create_article_id(link)

            # 같은 기사가 이미 들어갔다면 제외
            if any(
                item.get("article_id") == article_id
                for item in news_items
            ):
                continue

            
            news_items.append(
                {
                    "article_id": article_id,
                    "publisher_id": PUBLISHER_IDS[publisher],
                    "publisher": publisher,
                    "category": category,
                    "title": title,
                    "description": description,
                    "published_at": published,
                    "link": normalize_link(link),
                    "collected_at": datetime.now(timezone.utc).isoformat(),
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


def migrate_existing_article(
    item,
    current_time,
):
    """
    구형 기사 데이터를 현재 Article DB 스키마로 변환한다.

    구형 필드:
    - published

    현재 필드:
    - publisher_id
    - published_at
    - updated_at
    """
    if not isinstance(item, dict):
        return None

    migrated_item = item.copy()

    publisher = str(
        migrated_item.get("publisher") or ""
    ).strip()

    # 구형 published 필드를 published_at으로 이전
    if not migrated_item.get("published_at"):
        migrated_item["published_at"] = (
            migrated_item.get("published")
            or ""
        )

    # 언론사명을 기준으로 publisher_id 보완
    if not migrated_item.get("publisher_id"):
        migrated_item["publisher_id"] = (
            PUBLISHER_IDS.get(
                publisher,
                "",
            )
        )

    # article_id가 없으면 링크를 기준으로 생성
    if (
        not migrated_item.get("article_id")
        and migrated_item.get("link")
    ):
        migrated_item["article_id"] = (
            create_article_id(
                migrated_item["link"]
            )
        )

    # 최초 수집 시각이 없으면 현재 시각 사용
    if not migrated_item.get("collected_at"):
        migrated_item["collected_at"] = (
            current_time
        )

    # 수정 시각이 없으면 수집 시각을 기준으로 보완
    if not migrated_item.get("updated_at"):
        migrated_item["updated_at"] = (
            migrated_item.get("collected_at")
            or current_time
        )

    # 더 이상 사용하지 않는 구형 필드 제거
    migrated_item.pop(
        "published",
        None,
    )

    return migrated_item


def save_articles(news_items):
    output_path = Path("data/news.json")
    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    existing_items = []

    # 기존에 저장된 기사 불러오기
    if output_path.exists():
        try:
            with output_path.open(
                "r",
                encoding="utf-8",
            ) as file:
                loaded_data = json.load(file)

            if isinstance(loaded_data, list):
                existing_items = loaded_data

        except (
            json.JSONDecodeError,
            OSError,
        ) as error:
            print(
                f"기존 news.json 불러오기 실패: {error}"
            )
            print(
                "새로 수집한 기사만 저장합니다."
            )

    now = datetime.now(timezone.utc)
    current_time = now.isoformat()
    retention_cutoff = (
        now - timedelta(days=RETENTION_DAYS)
    )

    existing_articles = {}
    migrated_count = 0

    for item in existing_items:
        original_item = item.copy()

        migrated_item = migrate_existing_article(
            item,
            current_time,
        )

        if migrated_item is None:
            continue

        if migrated_item != original_item:
            migrated_count += 1

        article_id = migrated_item.get(
            "article_id"
        )

        if article_id:
            existing_articles[
                article_id
            ] = migrated_item

    # 기존 기사에 새 수집 결과를 병합
    article_map = dict(existing_articles)

    duplicate_count = 0
    removed_old_count = 0

    content_fields = (
        "publisher_id",
        "publisher",
        "category",
        "title",
        "description",
        "published_at",
        "link",
    )

    for new_item in news_items:
        article_id = new_item.get(
            "article_id"
        )

        if not article_id:
            continue

        existing_item = article_map.get(
            article_id
        )

        # 처음 저장되는 기사
        if existing_item is None:
            new_item["updated_at"] = (
                current_time
            )
            new_item["collected_at"] = (
                current_time
            )
            article_map[
                article_id
            ] = new_item
            continue

        # 기존 기사와 내용이 실제로 달라졌는지 확인
        content_changed = any(
            existing_item.get(field, "")
            != new_item.get(field, "")
            for field in content_fields
        )

        merged_item = (
            existing_item.copy()
        )

        for field in content_fields:
            merged_item[field] = (
                new_item.get(field, "")
            )

        # 재수집 시각은 항상 현재 시각으로 변경
        merged_item["collected_at"] = (
            current_time
        )

        # 실제 내용이 바뀐 경우에만 updated_at 갱신
        if content_changed:
            merged_item["updated_at"] = (
                current_time
            )
        else:
            merged_item["updated_at"] = (
                existing_item.get(
                    "updated_at"
                )
                or current_time
            )

        article_map[
            article_id
        ] = merged_item

        duplicate_count += 1

    # 30일이 지난 기사 제거
    merged_items = []

    for item in article_map.values():
        published_dt = (
            parse_published_datetime(
                item.get(
                    "published_at",
                    "",
                )
            )
        )

        if (
            published_dt
            and published_dt
            < retention_cutoff
        ):
            removed_old_count += 1
            continue

        merged_items.append(item)

    # 최신 기사 순으로 정렬
    merged_items.sort(
        key=lambda item: (
            parse_published_datetime(
                item.get(
                    "published_at",
                    "",
                )
            )
            or datetime.min.replace(
                tzinfo=timezone.utc
            )
        ),
        reverse=True,
    )

    with output_path.open(
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            merged_items,
            file,
            ensure_ascii=False,
            indent=2,
        )

    new_link_count = len(
        {
            item.get("article_id")
            for item in news_items
            if item.get("article_id")
        }
        - {
            item.get("article_id")
            for item in existing_items
            if item.get("article_id")
        }
    )

    print(
        f"\n이번 실행에서 수집한 기사: "
        f"{len(news_items)}개"
    )
    print(
        f"새로 추가된 기사: "
        f"{new_link_count}개"
    )
    print(
        f"중복으로 제외된 기사: "
        f"{duplicate_count}개"
    )
    print(
        f"구형 스키마 변환 기사: "
        f"{migrated_count}개"
    )
    print(
        f"30일 초과로 삭제된 기사: "
        f"{removed_old_count}개"
    )
    print(
        f"현재 저장된 전체 기사: "
        f"{len(merged_items)}개"
    )
    print(
        f"저장 위치: {output_path}"
    )
    print(
        "이 단계에서는 Solar API를 사용하지 않습니다."
    )


def main():
    news_items = collect_articles()
    save_articles(news_items)


if __name__ == "__main__":
    main()