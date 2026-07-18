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

검색어 "{query}"로 수집된 기사 목록을 분석하여, 동일한 구체적 사건을
직접 다룬 기사끼리 event group으로 묶으세요.

[Event Group의 정의]

Event Group은 단순히 주제, 검색어, 인물 또는 기관이 비슷한 기사 묶음이
아닙니다. 서로 다른 언론사가 동일한 하나의 구체적인 사건, 결정, 발언,
정책, 사고 또는 조치를 보도한 기사 집합이어야 합니다.

[Grouping 필수 기준]

1. 같은 event group에 포함되는 기사들은 동일한 하나의 구체적 사건을 다루어야 합니다. 사건 동일성은 다음 요소를 종합하여 판단하세요.

* 실제로 발생하거나 발표된 핵심 행위·결정·변화
* 사건의 주요 당사자·대상
* 사건이 발생한 시점·장소·상황
* 기사들이 공통으로 전제하는 구체적인 사실

2. 단순히 같은 검색어, 주제, 인물, 기관, 기업, 정책, 수사 또는 사회적 쟁점을 다룬다는 이유만으로 같은 사건으로 판단하지 마세요. 공통된 배경이나 상위 주제가 아니라, 기사들이 보도하는 핵심 행위·결정·변화가 동일해야 합니다.
3. 동일한 인물이나 기관이 등장하더라도, 각 기사에서 다루는 핵심 행위·결정·발표·사건이 다르면 별도의 event group으로 분리하세요.
4. 사건의 주요 인물이나 기관이 일부 다르더라도, 모든 기사가 동일한 중심 사건에서 직접 파생된 보도라면 같은 event group에 포함할 수 있습니다.
5. 동일한 사건으로 판단된 경우에는 기사별 보도 초점이 달라도 같은 event group에 포함하세요. 다음과 같은 차이는 동일 사건 내부의 다양한 관점으로 인정합니다.

* 사건 자체의 사실과 진행 상황
* 사건의 원인과 배경
* 사건이 미치는 영향과 결과
* 관계자·시장·정치권·사회 등의 반응
* 사건에 대한 평가와 의미
* 향후 전망과 예상되는 변화
* 사건 이후의 후속 조치와 대응

6. 기사 제목이나 설명에서 해당 기사가 그룹의 중심 사건을 직접 보도하거나, 그 사건의 원인·배경·영향·반응·평가·전망·후속 조치를 명확하게 다룬다는 연결 근거를 확인할 수 있어야 합니다.
7. 기사 작성일이나 후속 보도 시점이 다르다는 이유만으로 별개의 사건으로 판단하지 마세요. 다만 시점의 차이로 인해 서로 다른 행위·결정·발표가 발생했다면 별개의 사건으로 분리하세요.
8. 같은 검색어 또는 유사한 사건 유형을 다루더라도 장소, 대상, 핵심 행위 또는 사건의 구체적 사실이 다르면 해당 그룹에 포함하지 마세요.

[반드시 분리하거나 제외해야 하는 경우]

1. 공통된 검색어, 인물, 기관, 기업, 산업, 정책 또는 사회적 쟁점만 공유하고, 각 기사가 보도하는 핵심 행위·결정·변화가 다르면 서로 다른 event group으로 분리하세요.
2. 하나의 기사는 법안 처리, 다른 기사는 인물 소환, 또 다른 기사는 판결이나 영장 결과처럼 서로 다른 구체적 행위를 중심으로 다룬다면, 동일한 기관이나 사건군과 관련되어 있더라도 별개의 사건으로 판단하세요.
3. 검색어 "{query}"가 단순히 언급되었을 뿐 기사의 핵심 내용과 직접 관련되지 않으면 어떤 group에도 포함하지 마세요.
4. 일반적인 배경 설명, 장기 전망 또는 포괄적 해설만 다루고 있으며 특정한 중심 사건과의 직접적인 연결을 제목이나 설명에서 확인할 수 없다면 제외하세요.
5. 제목의 일부 단어, 검색어 또는 고유명사가 같다는 이유만으로 같은 사건으로 묶지 마세요.
6. 그룹의 label과 summary가 그룹 안의 모든 기사를 구체적이고 자연스럽게 설명할 수 없다면, 서로 다른 사건이 섞여 있는지 다시 검토하여 그룹을 분리하세요.


[운영 원칙]

- 하나의 기사를 여러 event group에 중복 포함하지 마세요.
- 각 event group에는 서로 다른 언론사의 기사가 최소 2건 이상
  포함되어야 합니다.
- 한 언론사만 보도한 사건은 event group으로 만들지 마세요.
- 실제로 하나의 사건만 존재하면 그룹 1개만 반환하세요.
- 서로 다른 사건이 존재하면 반드시 별도의 그룹으로 분리하세요.
- event group 수는 1개 이상 {maximum_group_count}개 이하로 작성하세요.
- label은 그룹의 모든 기사에 공통으로 적용되는 구체적인 사건명으로
  작성하세요.
- summary는 그룹 기사들이 공통으로 다루는 사실만 사용하여 1~2문장으로
  작성하세요.
- 내부 판단 과정은 출력하지 말고 최종 JSON만 반환하세요.
- Markdown 코드 블록이나 JSON 이외의 문장은 출력하지 마세요.

반드시 아래 JSON 구조로만 응답하세요.

{{
  "event_groups": [
    {{
      "group_id": "영문 소문자와 하이픈으로 작성한 그룹 ID",
      "label": "그룹 기사 모두에 공통으로 적용되는 구체적인 사건명",
      "summary": "그룹 기사들이 공통으로 다루는 사실 기반 사건 요약",
      "article_ids": [
        "이 사건을 직접 다루는 기사의 article_id"
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
