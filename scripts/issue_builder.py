"""
검색 결과(여러 언론사에 흩어진 개별 기사 랭킹 리스트)를 사건·쟁점 단위
Event Group으로 묶고, analyze_issue_batch()가 바로 쓸 수 있는 이슈 후보로
조립하는 모듈.

"Publisher Grouping"(analysis.py:group_publishers, 보도 태도로 언론사를 묶는
단계)과 헷갈리지 않도록, 이 모듈에서는 "event group(사건 그룹)"이라는 용어만
쓴다 — 여기서 묶는 기준은 보도 태도가 아니라 "무슨 사건을 다루는가"이다.
"""

from __future__ import annotations

import hashlib
import time
from typing import Any

from openai import OpenAI

from analysis import (
    MAX_RETRIES,
    RETRY_WAIT_SECONDS,
    clean_string,
    request_solar_analysis,
)
from search_engine import search_with_context


DEFAULT_PUBLISHER_LIMIT = 6
DEFAULT_MAX_CANDIDATES = 5
DEFAULT_MIN_SCORE_RATIO = 0.5
DEFAULT_MAX_POOL_SIZE = 40

MAXIMUM_EVENT_GROUP_COUNT = 5


def select_representative_articles(
    ranked_results: list[dict[str, Any]],
    n_publishers: int = DEFAULT_PUBLISHER_LIMIT,
) -> list[dict[str, Any]]:
    """
    랭킹순으로 정렬된 기사 목록에서 언론사별 최고 순위 기사 1건만 남기고,
    상위 n_publishers개 언론사만 채택한다.
    """
    representative_by_publisher: dict[str, dict[str, Any]] = {}

    for article in ranked_results:
        publisher_id = str(article.get("publisher_id") or "").strip()

        if not publisher_id:
            continue

        if publisher_id in representative_by_publisher:
            continue

        representative_by_publisher[publisher_id] = article

        if len(representative_by_publisher) >= n_publishers:
            break

    return list(representative_by_publisher.values())


def filter_candidate_pool(
    ranked_results: list[dict[str, Any]],
    min_score_ratio: float = DEFAULT_MIN_SCORE_RATIO,
    max_pool_size: int = DEFAULT_MAX_POOL_SIZE,
) -> list[dict[str, Any]]:
    """
    Event Grouping에 넣을 후보 풀을 구성한다.

    similarity_score(임베딩 유사도)만으로는 노이즈와 실제 관련 기사가 잘
    분리되지 않는다 (실측 결과 노이즈와 관련 기사의 similarity_score 범위가
    겹쳤다). 대신 rank_results()가 이미 계산해 정렬 기준으로 쓰는 종합 점수
    (score: 제목/본문 키워드 일치 + 유사도 가중 + 최신성)를 기준으로,
    최상위 결과 대비 min_score_ratio 이상인 기사만 남기고 그중 랭킹 상위
    max_pool_size건으로 자른다.
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


def build_event_grouping_prompt(
    query: str,
    articles: list[dict[str, Any]],
) -> str:
    """
    검색 결과를 사건·쟁점 단위 event group으로 묶기 위한 Solar 프롬프트를 생성한다.
    """
    articles_text = "\n\n====================\n\n".join(
        f"""
article_id: {article["article_id"]}
언론사: {article.get("publisher", "")}
제목: {article.get("title", "")}
설명: {article.get("description", "")}
""".strip()
        for article in articles
    )

    maximum_group_count = min(
        MAXIMUM_EVENT_GROUP_COUNT,
        len(articles),
    )

    return f"""
당신은 뉴스 기사 비교 서비스 Prism의 Event Grouping(사건 그룹화) 분석기입니다.

입력 데이터는 검색어 "{query}"로 찾은 기사 목록입니다. 이 기사들을 같은
사건·쟁점을 다루는 것끼리 event group으로 묶으세요. 언론사의 보도 태도나
논조가 아니라, "무슨 일이 있었는지"를 기준으로 묶어야 합니다.

Event Grouping 원칙:
- 같은 사건·쟁점을 다루는 기사끼리만 같은 event group으로 묶으세요.
- 서로 다른 사건이면 반드시 다른 event group으로 구분하세요.
- 검색 결과가 실제로 하나의 사건만 다루고 있다면 event group을 1개만
  반환하세요. 억지로 2개 이상으로 쪼개지 마세요.
- 검색어 "{query}"와 실질적으로 무관한 기사는 어떤 group에도 포함하지
  말고 결과에서 제외하세요.
- 각 event group에는 서로 다른 언론사의 기사가 최소 2건 이상 포함되어야
  의미가 있습니다. 언론사가 1곳뿐인 사건은 만들지 마세요.
- event group 수는 1개 이상 {maximum_group_count}개 이하로 작성하세요.
- JSON 이외의 문장은 출력하지 마세요.

반드시 아래 JSON 구조로만 응답하세요.

{{
  "event_groups": [
    {{
      "group_id": "영문 소문자와 하이픈으로 작성한 그룹 ID",
      "label": "이 사건을 한 문장으로 표현한 제목",
      "summary": "이 사건이 무엇에 관한 것인지 1~2문장 요약",
      "article_ids": [
        "이 사건에 속한 기사의 article_id"
      ]
    }}
  ]
}}

검색 결과 기사 목록:

{articles_text}
""".strip()


def validate_event_groups(
    result: Any,
    valid_article_ids: set[str],
) -> list[dict[str, Any]]:
    """
    Solar의 Event Grouping 결과를 검증하고 정리한다.
    """
    if not isinstance(result, dict):
        raise ValueError(
            "Event Grouping 결과의 최상위 값이 객체가 아닙니다."
        )

    event_groups = result.get("event_groups")

    if not isinstance(event_groups, list):
        raise ValueError("event_groups는 배열이어야 합니다.")

    if not event_groups:
        raise ValueError("생성된 event group이 없습니다.")

    normalized_groups = []
    seen_group_ids: set[str] = set()

    for index, group in enumerate(
        event_groups[:MAXIMUM_EVENT_GROUP_COUNT],
        start=1,
    ):
        if not isinstance(group, dict):
            continue

        group_id = clean_string(group.get("group_id"))

        if not group_id:
            group_id = f"event-group-{index}"

        if group_id in seen_group_ids:
            group_id = f"{group_id}-{index}"

        seen_group_ids.add(group_id)

        label = clean_string(group.get("label"))
        summary = clean_string(group.get("summary"))

        raw_article_ids = group.get("article_ids", [])

        if not isinstance(raw_article_ids, list):
            raw_article_ids = []

        valid_ids = []
        seen_ids: set[str] = set()

        for article_id in raw_article_ids:
            article_id = clean_string(article_id)

            if not article_id or article_id in seen_ids:
                continue

            if article_id not in valid_article_ids:
                continue

            seen_ids.add(article_id)
            valid_ids.append(article_id)

        if not label or len(valid_ids) < 2:
            continue

        normalized_groups.append(
            {
                "group_id": group_id,
                "label": label,
                "summary": summary,
                "article_ids": valid_ids,
            }
        )

    return normalized_groups


def check_candidate_quality(
    candidate: dict[str, Any],
) -> dict[str, Any] | None:
    """
    사용자에게 보여줄 만한, 실제로 언론사별 비교가 가능한 이슈 후보인지 검증한다.

    analyze_issue_batch()가 언론사별 분석 단계에서 다시 한번 검증하긴 하지만,
    "비교 가능한 이슈만 후보로 보여준다"는 의도를 이 단계에서 명확히 드러내기
    위해 별도 함수로 분리한다.
    """
    if not clean_string(candidate.get("issue_title")):
        return None

    valid_publishers = [
        item
        for item in candidate.get("publishers", [])
        if item.get("articles")
        and clean_string(item["articles"][0].get("title"))
        and clean_string(item["articles"][0].get("link"))
    ]

    if len(valid_publishers) < 2:
        return None

    candidate["publishers"] = valid_publishers

    return candidate


def build_issue_candidates(
    client: OpenAI,
    query: str,
    max_candidates: int = DEFAULT_MAX_CANDIDATES,
    n_publishers: int = DEFAULT_PUBLISHER_LIMIT,
) -> dict[str, Any]:
    """
    검색어를 받아 이슈 후보 목록(analyze_issue_batch()가 바로 쓸 수 있는 형태)을
    만든다. 각 후보는 하나의 event group(사건)에 해당한다.
    """
    normalized_query = str(query or "").strip()

    if not normalized_query:
        raise ValueError("검색어가 비어 있습니다.")

    search_context = search_with_context(normalized_query)
    ranked_results = search_context.get("results", [])

    candidate_pool = filter_candidate_pool(ranked_results)

    if len(candidate_pool) < 2:
        raise ValueError(
            "이 검색어로는 비교할 수 있는 기사가 부족합니다."
        )

    articles_by_id = {
        article["article_id"]: article
        for article in candidate_pool
    }

    prompt = build_event_grouping_prompt(
        normalized_query,
        candidate_pool,
    )

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
                set(articles_by_id),
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

    candidates = []
    excluded_count = 0

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

        if len(representative_articles) < 2:
            excluded_count += 1
            continue

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
