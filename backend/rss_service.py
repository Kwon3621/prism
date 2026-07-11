from typing import Any

import feedparser

SBS_RSS_URL = (
    "https://news.sbs.co.kr/news/"
    "newsflashRssFeed.do?plink=RSSREADER"
)


def get_sbs_articles(query: str = "") -> list[dict[str, Any]]:
    """
    SBS RSS에서 기사를 가져오고,
    검색어가 있으면 제목과 설명을 기준으로 필터링합니다.
    """
    feed = feedparser.parse(SBS_RSS_URL)

    if feed.bozo and not feed.entries:
        raise RuntimeError("SBS RSS 피드를 불러오지 못했습니다.")

    normalized_query = query.strip().lower()
    articles: list[dict[str, Any]] = []

    for entry in feed.entries:
        title = entry.get("title", "").strip()
        summary = entry.get("summary", "").strip()
        link = entry.get("link", "").strip()
        published = entry.get("published", "").strip()

        searchable_text = f"{title} {summary}".lower()

        if normalized_query and normalized_query not in searchable_text:
            continue

        articles.append(
            {
                "media": "SBS 뉴스",
                "title": title,
                "summary": summary,
                "link": link,
                "published": published,
            }
        )

    return articles


# 샘플 Python 스크립트입니다.

# Shift+F10을(를) 눌러 실행하거나 내 코드로 바꿉니다.
# 클래스, 파일, 도구 창, 액션 및 설정을 어디서나 검색하려면 Shift 두 번을(를) 누릅니다.


def print_hi(name):
    # 스크립트를 디버그하려면 하단 코드 줄의 중단점을 사용합니다.
    print(f'Hi, {name}')  # 중단점을 전환하려면 Ctrl+F8을(를) 누릅니다.


# 스크립트를 실행하려면 여백의 녹색 버튼을 누릅니다.
if __name__ == '__main__':
    print_hi('PyCharm')

# https://www.jetbrains.com/help/pycharm/에서 PyCharm 도움말 참조
