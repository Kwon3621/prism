"""
[Legacy / 미사용] 핫토픽 배치가 카테고리명("정치"/"경제"/"사회")을 검색어로
그대로 써서 후보 풀을 채점하던 이전 방식.

2026-07-21 리팩토링으로 build_featured_issues.py는 카테고리명을
issue_builder.extract_query_keywords()에 먼저 넣어 구체적 키워드로 좁힌 뒤,
그 키워드로 issue_builder.build_issue_candidates()(검색 경로와 동일한 함수)를
호출하는 방식으로 바뀌었다. 넓은 카테고리명을 관련도 컷 비율만 조절해서
직접 Event Grouping에 넣는 이 방식은 (HOT_TOPIC_MIN_SCORE_RATIO를
0.15/0.3/0.5 등으로 바꿔가며 테스트해봐도) 오배정을 일관되게 줄이지
못한다고 결론 내려서 더 이상 쓰지 않는다. 롤백 대비용으로 코드만 남겨둔다.
"""

from __future__ import annotations

import hashlib
import time
from datetime import datetime, timezone
from typing import Any

from openai import OpenAI

from analysis import MAX_RETRIES, RETRY_WAIT_SECONDS, request_solar_analysis
from search_engine import search_with_context

from issue_builder import (
    DEFAULT_MAX_CANDIDATES,
    DEFAULT_MAX_POOL_SIZE,
    DEFAULT_PUBLISHER_LIMIT,
    build_event_grouping_prompt,
    check_candidate_quality,
    select_representative_articles,
    validate_event_groups,
)


# 검색 경로(issue_builder.DEFAULT_MIN_SCORE_RATIO=0.5)보다 훨씬 가벼운 컷.
# "정치"/"경제" 같은 넓은 카테고리 검색어는 관련 기사 자체가 원래 넓게
# 퍼져 있어서 0.5처럼 세게 자르면 진짜 사건들까지 후보 풀에서 빠질 수
# 있다. 그렇다고 전혀 안 거르면 Solar가 사실상 무관한 기사를 그룹에
# 섞어 넣는 오배정이 늘어나서, 최상위 점수 대비 이 비율 미만인, 확실히
# 노이즈인 기사만 걸러낸다.
HOT_TOPIC_MIN_SCORE_RATIO = 0.15

# 사건 묶음 자체를 채점할 때 쓰는 값.
# "언론사 수 + 기사 수 + 최신성" 가중 합산으로 사건의 비중을 매긴다.
GROUP_RECENCY_WINDOW_HOURS = 24
GROUP_PUBLISHER_COUNT_CAP = DEFAULT_PUBLISHER_LIMIT
GROUP_ARTICLE_COUNT_CAP = 10
GROUP_PUBLISHER_WEIGHT = 0.5
GROUP_ARTICLE_WEIGHT = 0.3
GROUP_RECENCY_WEIGHT = 0.2


def cap_candidate_pool(
    ranked_results: list[dict[str, Any]],
    max_pool_size: int = DEFAULT_MAX_POOL_SIZE,
    min_score_ratio: float = HOT_TOPIC_MIN_SCORE_RATIO,
) -> list[dict[str, Any]]:
    """
    핫토픽 배치용 후보 풀을 구성한다.

    검색 경로(filter_candidate_pool)만큼 세게 거르진 않는다 — 핫토픽은
    "이 기사가 검색어와 얼마나 관련 있어 보이는가"가 아니라 사건으로
    묶은 뒤 "그 사건을 몇 개 언론사·기사가, 얼마나 최근에 다뤘는가"로
    판단해야 하므로 관련 후보를 넓게 남겨둬야 한다. 다만 전혀 안 거르면
    Solar가 사실상 무관한 기사를 그룹에 섞어 넣는 오배정이 늘어나서,
    최상위 점수 대비 min_score_ratio 미만인 확실한 노이즈만 가볍게
    걸러내고 랭킹 상위 max_pool_size건으로 자른다.
    """
    if not ranked_results:
        return []

    top_score = float(ranked_results[0].get("score") or 0.0)
    score_floor = top_score * min_score_ratio

    filtered = [
        article
        for article in ranked_results
        if float(article.get("score") or 0.0) >= score_floor
    ]

    return filtered[:max_pool_size]


def parse_published_datetime(published: str) -> datetime | None:
    """
    기사 발행 시각 문자열을 UTC datetime으로 변환한다.

    generate_news.py에도 같은 이름의 함수가 있지만, 그 모듈은 최상단에서
    feedparser를 import한다. Vercel의 api/index.py는 issue_builder를
    불러오는데, feedparser는 루트 requirements.txt(서버리스 함수용)에는
    없어서 그쪽 모듈을 import하면 API 전체가 죽는다. 그래서 stdlib만
    쓰는 이 파싱 로직만 여기 그대로 복사해 둔다.
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


def score_event_group(
    group_articles: list[dict[str, Any]],
    now: datetime,
) -> float:
    """
    사건 묶음 하나를 "언론사 수 + 기사 수 + 최신성" 가중 합산으로 채점한다.

    최신성은 묶음 안에서 가장 오래된 기사의 발행 시각을 기준으로 계산한다.
    최신 기사가 하나 섞여 있어도 나머지가 다 오래됐다면 지금 한창 다뤄지는
    사건은 아니라고 보기 때문이다.
    """
    publisher_count = len(
        {
            article.get("publisher_id")
            for article in group_articles
        }
    )
    article_count = len(group_articles)

    published_at_list = [
        parse_published_datetime(article.get("published_at"))
        for article in group_articles
    ]
    published_at_list = [
        value for value in published_at_list if value
    ]

    if published_at_list:
        oldest_age_hours = (
            now - min(published_at_list)
        ).total_seconds() / 3600
    else:
        oldest_age_hours = GROUP_RECENCY_WINDOW_HOURS

    recency_score = max(
        0.0,
        1 - (oldest_age_hours / GROUP_RECENCY_WINDOW_HOURS),
    )
    publisher_score = (
        min(publisher_count, GROUP_PUBLISHER_COUNT_CAP)
        / GROUP_PUBLISHER_COUNT_CAP
    )
    article_score = (
        min(article_count, GROUP_ARTICLE_COUNT_CAP)
        / GROUP_ARTICLE_COUNT_CAP
    )

    return (
        GROUP_PUBLISHER_WEIGHT * publisher_score
        + GROUP_ARTICLE_WEIGHT * article_score
        + GROUP_RECENCY_WEIGHT * recency_score
    )


def build_ranked_event_candidates(
    client: OpenAI,
    query: str,
    max_candidates: int = DEFAULT_MAX_CANDIDATES,
    n_publishers: int = DEFAULT_PUBLISHER_LIMIT,
) -> dict[str, Any]:
    """
    [Legacy] 핫토픽 배치(build_featured_issues.py) 전용 이슈 후보 생성 함수.

    issue_builder.build_issue_candidates()는 사용자가 입력한 검색어와의
    관련도로 후보를 먼저 거른 뒤 그룹핑하지만, 이 함수는 관련도 컷 없이
    먼저 Event Grouping을 실행하고, 만들어진 사건 묶음을 언론사 수·기사
    수·최신성 종합 점수(score_event_group)로 평가해 점수가 높은 순으로
    채택한다. "정치"/"경제"/"사회" 같은 넓은 카테고리 검색어는 관련도
    점수 자체가 사건의 비중을 대변하지 못하기 때문이다.
    """
    normalized_query = str(query or "").strip()

    if not normalized_query:
        raise ValueError("검색어가 비어 있습니다.")

    search_context = search_with_context(normalized_query)
    ranked_results = search_context.get("results", [])

    candidate_pool = cap_candidate_pool(ranked_results)

    if len(candidate_pool) < 2:
        raise ValueError(
            "이 검색어로는 비교할 수 있는 기사가 부족합니다."
        )

    prompt = build_event_grouping_prompt(
        normalized_query,
        candidate_pool,
    )

    valid_article_ids = {
        article["article_id"] for article in candidate_pool
    }

    last_error = None
    event_groups = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            print(
                "[Event Grouping] "
                f"{attempt}/{MAX_RETRIES}"
            )

            raw_result = request_solar_analysis(
                client=client,
                prompt=prompt,
            )

            event_groups = validate_event_groups(
                raw_result,
                valid_article_ids,
            )

            break

        except Exception as error:
            last_error = error

            print(
                "[Event Grouping 실패] "
                f"{attempt}/{MAX_RETRIES}: {error}"
            )

            if attempt < MAX_RETRIES:
                time.sleep(RETRY_WAIT_SECONDS)

    if event_groups is None:
        raise RuntimeError(
            "Event Grouping이 "
            f"{MAX_RETRIES}회 모두 실패했습니다: {last_error}"
        )

    now = datetime.now(timezone.utc)
    scored_groups = []

    for group in event_groups:
        article_id_set = set(group["article_ids"])

        group_articles_ranked = [
            article
            for article in candidate_pool
            if article["article_id"] in article_id_set
        ]

        representative_articles = select_representative_articles(
            group_articles_ranked,
            n_publishers=n_publishers,
        )

        # 서로 다른 언론사 2곳 미만이면 애초에 "여러 언론사가 다룬 사건"이
        # 아니므로 점수를 매길 필요 없이 제외한다.
        if len(representative_articles) < 2:
            continue

        group_score = score_event_group(
            group_articles_ranked,
            now,
        )

        scored_groups.append(
            (group_score, group, representative_articles)
        )

    # 사건 묶음 자체의 비중(언론사 수·기사 수·최신성) 순으로 정렬한다.
    scored_groups.sort(
        key=lambda item: item[0],
        reverse=True,
    )

    candidates = []
    excluded_count = len(event_groups) - len(scored_groups)

    for group_score, group, representative_articles in scored_groups:
        representative_article_ids = sorted(
            article["article_id"]
            for article in representative_articles
        )

        issue_id = "issue-" + hashlib.sha1(
            (
                f"{normalized_query.lower()}|"
                f"{','.join(representative_article_ids)}"
            ).encode("utf-8")
        ).hexdigest()[:16]

        candidate = {
            "issue_id": issue_id,
            "issue_title": group["label"],
            "summary": group["summary"],
            "query": normalized_query,
            "expanded_queries": search_context.get(
                "expanded_queries",
                [],
            ),
            "group_score": round(group_score, 4),
            "publishers": [
                {
                    "publisher_id": article["publisher_id"],
                    "publisher": article["publisher"],
                    "articles": [article],
                }
                for article in representative_articles
            ],
        }

        checked_candidate = check_candidate_quality(candidate)

        if checked_candidate is None:
            excluded_count += 1
            continue

        candidates.append(checked_candidate)

    if not candidates:
        raise ValueError("비교 가능한 이슈를 찾지 못했습니다.")

    return {
        "candidates": candidates[:max_candidates],
        "excluded_count": excluded_count,
        "expanded_queries": search_context.get(
            "expanded_queries",
            [],
        ),
    }
