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
from datetime import datetime, timezone
from typing import Any

from openai import OpenAI

from analysis import (
    MAX_RETRIES,
    RETRY_WAIT_SECONDS,
    clean_string,
    request_solar_analysis,
)
from cache import get_keyword_extraction, save_keyword_extraction
from search_engine import search_with_context
from vector_store import get_records_data_version


DEFAULT_PUBLISHER_LIMIT = 6
DEFAULT_MAX_CANDIDATES = 5
DEFAULT_MIN_SCORE_RATIO = 0.5
DEFAULT_MAX_POOL_SIZE = 40

MAXIMUM_EVENT_GROUP_COUNT = 5

# extract_query_keywords() 전용 — "정치"/"경제"/"사회"처럼 넓은 검색어를
# 구체적인 키워드로 좁히는 단계라 필터링 없이 랭킹 상위만 넓게 본다.
# (관련도 컷을 걸면 "사회"처럼 후보 자체가 통째로 걸러져 실패하는
# 경우가 있었다.)
KEYWORD_EXTRACTION_POOL_SIZE = 60
MAXIMUM_KEYWORD_COUNT = 8
# 한 언론사만 다룬 키워드는 "여러 언론사가 다루는 구체적 사건"이 아니므로
# 후보에서 제외한다 (build_issue_candidates의 2곳 이상 기준과 동일한 원칙).
KEYWORD_MIN_PUBLISHER_COUNT = 2
# 프롬프트에 넣는 기사 설명(description) 길이 상한. 실측 결과 전체 길이를
# 넣어도 분류 품질은 비슷했고, 프롬프트 토큰만 줄여 응답 속도가 개선됐다.
KEYWORD_DESCRIPTION_MAX_LENGTH = 150


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

    return merge_overlapping_groups(normalized_groups)


GROUP_OVERLAP_MERGE_THRESHOLD = 0.5


def merge_overlapping_groups(
    groups: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    같은 사건을 가리키는 event group이 여러 개로 쪼개진 경우를 하나로 합친다.

    Solar가 "실제로 하나의 사건만 존재하면 그룹 1개만 반환하세요"라는
    지시를 어기고, 같은 핵심 기사에 매번 다른 언론사 기사 하나씩만 짝지어
    거의 동일한 그룹을 여러 개 반환하는 경우가 있다. 두 그룹의 article_ids가
    (더 작은 쪽 기준으로) GROUP_OVERLAP_MERGE_THRESHOLD 이상 겹치면 같은
    사건으로 보고 기사 목록을 합친다. 기준을 "더 작은 쪽 대비 비율"로 잡은
    건, 기사 하나가 여러 사건에 걸쳐 있어서 그룹 사이에 기사가 조금
    겹치는 정상적인 경우까지 합쳐버리지 않기 위해서다.
    """
    merged_groups: list[dict[str, Any]] = []

    for group in groups:
        group_id_set = set(group["article_ids"])

        target = None

        for kept in merged_groups:
            kept_id_set = set(kept["article_ids"])

            smaller_size = min(
                len(group_id_set),
                len(kept_id_set),
            )

            if smaller_size == 0:
                continue

            overlap_ratio = (
                len(group_id_set & kept_id_set)
                / smaller_size
            )

            if overlap_ratio >= GROUP_OVERLAP_MERGE_THRESHOLD:
                target = kept
                break

        if target is None:
            merged_groups.append(group)
            continue

        # 순서를 유지하면서 기사 목록만 합친다 (label/summary는 먼저
        # 나온 그룹 것을 그대로 쓴다).
        target["article_ids"] = list(
            dict.fromkeys(
                target["article_ids"]
                + group["article_ids"]
            )
        )

    return merged_groups


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



def build_event_keyword_prompt(
    query: str,
    articles: list[dict[str, Any]],
) -> str:
    """
    "정치"/"경제"/"사회"처럼 넓은 검색어로 모은 기사 목록에서, 여러
    언론사가 공통으로 다루는 구체적인 키워드(인물·사건·정책 등)를 뽑기
    위한 Solar 프롬프트를 생성한다.

    기사를 article_id(수십 자짜리 해시 문자열)로 인용하게 하면, 후보가
    60개까지 늘어났을 때 모델이 그 긴 문자열을 베끼다가 서로 다른 두
    article_id를 뒤섞어 존재하지 않는 값을 만들어내는 경우가 실측
    확인됐다(예: 두 실제 id의 뒷부분이 짜깁기된 값). 숫자는 긴 해시보다
    훨씬 안정적으로 재현되므로, article_id 대신 1부터 시작하는 번호로
    인용하게 하고 코드에서 번호→article_id로 역매핑한다.

    설명(description)은 150자로 자른다 — 실측 결과 전체 길이를 다 넣어도
    분류 품질은 비슷했고, 프롬프트 토큰만 줄여서 응답 속도를 개선한다.
    """
    articles_text = "\n\n====================\n\n".join(
        f"""
번호: {index}
언론사: {article.get("publisher", "")}
제목: {article.get("title", "")}
설명: {(article.get("description", "") or "")[:KEYWORD_DESCRIPTION_MAX_LENGTH]}
""".strip()
        for index, article in enumerate(articles, start=1)
    )

    return f"""
당신은 뉴스 기사 비교 서비스 Prism의 키워드 추출 분석기입니다.

검색어 "{query}"로 수집된 기사 목록에서, 여러 언론사가 공통으로 다루는
구체적인 인물, 사건, 정책, 기관 조치를 키워드로 추출하세요.

[키워드로 추출해야 하는 것]

- 검색하면 하나의 구체적 사건·쟁점으로 좁혀지는 고유명사 또는 짧은
  구체적 표현 (예: "정청래", "레버리지 ETF 규제", "장동혁 제헌절 불참")
- 반드시 서로 다른 언론사의 기사 2건 이상에서 반복 등장해야 합니다.

[키워드로 추출하면 안 되는 것]

- "{query}"처럼 여전히 넓은 범주 명사나 일반 명사(예: "국회", "경제
  정책", "물가", "사회 갈등")
- 기사 1건에서만 등장하는 지엽적 단어나 세부 수치
- 단순히 같은 인물·기관이 등장한다는 이유만으로 묶은 키워드. 같은
  인물이라도 서로 다른 발언·사건·결정을 다루면 별개의 키워드로
  분리하세요 (예: "정청래" 한 명에 대해서도 "후원금 쇄도"와 "후원회장
  인선"은 서로 다른 결정이므로 다른 키워드로 분리).

[작성 방법]

1. 후보 기사들을 훑어보고, 같은 키워드가 서로 다른 언론사·기사에서
   반복 등장하는지 확인하세요.
2. 키워드마다 그 키워드를 실제로 다루는 기사의 번호(위 기사 목록의
   "번호")를 모으세요. 목록에 실제로 있는 번호만 사용하고, 번호를
   만들어내거나 다른 번호와 섞지 마세요.
3. 서로 다른 언론사 기사가 2건 이상 걸리는 키워드만 포함하세요.
   해당하는 기사가 2건 미만이면 그 키워드는 아예 포함하지 마세요 —
   기사 수를 채우려고 그 키워드와 무관하거나 배경으로만 살짝 스친
   기사를 끼워 넣지 마세요.
4. 키워드마다 그 키워드에 속한 기사들이 공통으로 다루는 사실만으로
   1~2문장의 summary를 작성하세요. 이 summary는 재검색 없이 그대로
   사용자에게 노출됩니다.
5. 키워드는 최대 {MAXIMUM_KEYWORD_COUNT}개까지, 언급 비중(기사 수·언론사
   수)이 큰 순서로 정렬하세요.
6. 내부 판단 과정은 출력하지 말고 최종 JSON만 반환하세요.
7. Markdown 코드 블록이나 JSON 이외의 문장은 출력하지 마세요.

반드시 아래 JSON 구조로만 응답하세요.

{{
  "keywords": [
    {{
      "keyword": "짧고 구체적인 키워드 또는 사건명",
      "summary": "이 키워드에 속한 기사들이 공통으로 다루는 사실 요약",
      "article_indexes": [
        "이 키워드를 직접 다루는 기사의 번호(정수)"
      ]
    }}
  ]
}}

검색어: "{query}"

기사 목록:

{articles_text}
""".strip()


def validate_extracted_keywords(
    result: Any,
    candidate_pool: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Solar의 키워드 추출 결과를 검증하고 정리한다.

    "정치"/"경제"/"사회"처럼 후보 풀이 60개 가까이 되고 서로 무관한
    기사들로 넓게 뒤섞여 있으면, Solar가 article_id(수십 자짜리 해시)를
    그대로 베끼다가 서로 다른 두 article_id를 뒤섞어 존재하지 않는
    값을 만들어내는 경우가 실측 확인됐다. 그래서 프롬프트에서 article_id
    대신 1부터 시작하는 번호(article_indexes)로 인용하게 했고, 여기서는
    그 번호를 candidate_pool의 실제 인덱스로 되돌려 article_id를 구한다
    (범위를 벗어난 번호는 버린다).

    최종 채택 여부(서로 다른 언론사 2곳 이상 등)는 extract_query_keywords()가
    다시 판단한다 — 이 함수는 형식과 번호 유효성만 정리한다.
    """
    if not isinstance(result, dict):
        raise ValueError(
            "키워드 추출 결과의 최상위 값이 객체가 아닙니다."
        )

    raw_keywords = result.get("keywords")

    if not isinstance(raw_keywords, list):
        raise ValueError("keywords는 배열이어야 합니다.")

    if not raw_keywords:
        raise ValueError("추출된 키워드가 없습니다.")

    normalized_keywords = []
    seen_keywords: set[str] = set()

    for item in raw_keywords[:MAXIMUM_KEYWORD_COUNT]:
        if not isinstance(item, dict):
            continue

        keyword = clean_string(item.get("keyword"))

        if not keyword or keyword in seen_keywords:
            continue

        summary = clean_string(item.get("summary"))

        raw_indexes = item.get("article_indexes", [])

        if not isinstance(raw_indexes, list):
            raw_indexes = []

        article_ids = []
        seen_ids: set[str] = set()

        for raw_index in raw_indexes:
            try:
                index = int(raw_index)
            except (TypeError, ValueError):
                continue

            position = index - 1

            if position < 0 or position >= len(candidate_pool):
                continue

            article_id = candidate_pool[position]["article_id"]

            if article_id in seen_ids:
                continue

            seen_ids.add(article_id)
            article_ids.append(article_id)

        if len(article_ids) < 2:
            continue

        seen_keywords.add(keyword)
        normalized_keywords.append(
            {
                "keyword": keyword,
                "summary": summary,
                "article_ids": article_ids,
            }
        )

    return normalized_keywords


def keyword_search_tokens(keyword: str) -> list[str]:
    """
    키워드 문자열에서 대조에 쓸 핵심 토큰만 남긴다.

    "영업 중단"의 "영업"/"중단"처럼 흔한 2글자 일반 명사는 무관한
    기사에도 우연히 등장해서 대조 필터를 무력화시킨다(실측 확인 —
    "홈플러스" 검색에서 인사 발령 기사가 "영업 중단" 키워드에 잘못
    끼어듦). 개별 단어를 일일이 블랙리스트에 올리는 대신, 구체적인
    고유명사·사건명은 대부분 3글자 이상이라는 점을 이용해 3글자 이상
    토큰을 우선 쓴다. 그런 토큰이 하나도 없을 때만 2글자 토큰으로,
    그마저 없으면 원본 그대로 폴백한다.
    """
    words = keyword.split()

    return (
        [word for word in words if len(word) >= 3]
        or [word for word in words if len(word) >= 2]
        or words
    )


def article_matches_keyword_tokens(
    article: dict[str, Any],
    tokens: list[str],
) -> bool:
    """
    기사의 title/description에 키워드 토큰이 하나도 안 겹치면
    이 기사는 그 키워드와 무관하다고 본다 — Solar가 배경 설명이나
    다른 기사를 착각해서 끼워 넣는 경우를 코드 레벨에서 걸러낸다.
    """
    haystack = (
        f"{article.get('title', '')} {article.get('description', '')}"
    )

    return any(token in haystack for token in tokens)


def extract_query_keywords(
    client: OpenAI,
    query: str,
    max_keywords: int = MAXIMUM_KEYWORD_COUNT,
) -> dict[str, Any]:
    """
    넓은 검색어(예: "정치")로 모은 후보 기사 풀에서, 실제로 여러
    언론사가 공통으로 다루는 구체적인 키워드(인물·사건 등)를 추출한다.

    반환된 키워드마다 이미 검증된 article_ids(서로 다른 언론사 2곳
    이상)와 summary가 함께 붙어 있어서, build_candidate_from_keyword()가
    이 결과만으로 바로 비교 카드를 만들 수 있다. 키워드로 검색을 다시
    실행하지 않는 이유는, 그렇게 하면 그 키워드와 무관한 최근 기사들이
    새 후보 풀에 섞여 들어오고(예: "언더도그 전략"으로 재검색하면
    레버리지 ETF, 코스피 급락처럼 전혀 무관한 그룹이 같이 나옴), 희귀한
    키워드는 관련도 컷을 통과하는 기사가 2건 미만이 되어 재검색 자체가
    실패하기도 하기 때문이다. 이미 이 함수 안에서 한 번 검증한 후보
    풀을 그대로 재사용하는 게 더 정확하고 빠르다.

    관련도 컷(filter_candidate_pool)을 쓰지 않는다 — 넓은 검색어는
    관련도 점수 자체가 신호가 되지 못하고("정치" 검색에서 상위 스코어
    기사와 하위 스코어 기사가 똑같이 유효한 정치 기사일 수 있음), 컷을
    걸면 "사회"처럼 후보 풀 전체가 걸러져 실패하는 경우가 있었다.
    """
    normalized_query = str(query or "").strip()

    if not normalized_query:
        raise ValueError("검색어가 비어 있습니다.")

    search_context = search_with_context(normalized_query)
    ranked_results = search_context.get("results", [])
    candidate_pool = ranked_results[:KEYWORD_EXTRACTION_POOL_SIZE]

    if len(candidate_pool) < 2:
        raise ValueError(
            "이 검색어로는 키워드를 추출할 기사가 부족합니다."
        )

    articles_by_id = {
        article["article_id"]: article
        for article in candidate_pool
    }

    # 같은 검색어가 반복 요청되는 경우(인기 검색어, 핫토픽 카테고리 등)
    # Solar 호출(요청당 6~12초) 자체를 건너뛴다. records.json이 갱신되기
    # 전까지만 유효하도록 data_version을 키에 포함시킨다 — 새 기사가
    # 들어오면 자동으로 무효화된다.
    data_version = get_records_data_version()
    cached_result = get_keyword_extraction(
        normalized_query,
        data_version,
    )

    if cached_result is not None:
        scored_keywords = cached_result.get("keywords", [])
    else:
        scored_keywords = _extract_and_score_keywords(
            client,
            normalized_query,
            candidate_pool,
            articles_by_id,
        )

        save_keyword_extraction(
            normalized_query,
            data_version,
            {"keywords": scored_keywords},
        )

    return {
        "query": normalized_query,
        "keywords": scored_keywords[:max_keywords],
        "articles_by_id": articles_by_id,
    }


def _extract_and_score_keywords(
    client: OpenAI,
    normalized_query: str,
    candidate_pool: list[dict[str, Any]],
    articles_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    extract_query_keywords()의 캐시 미스 경로 — 실제로 Solar를 호출해
    키워드를 뽑고 검증·병합·채점까지 마친 최종 목록을 반환한다.
    """
    prompt = build_event_keyword_prompt(
        normalized_query,
        candidate_pool,
    )

    last_error = None
    raw_keywords = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            print(f"[키워드 추출] {attempt}/{MAX_RETRIES}")

            raw_result = request_solar_analysis(
                client=client,
                prompt=prompt,
            )

            raw_keywords = validate_extracted_keywords(
                raw_result,
                candidate_pool,
            )

            break

        except Exception as error:
            last_error = error

            print(
                "[키워드 추출 실패] "
                f"{attempt}/{MAX_RETRIES}: {error}"
            )

            if attempt < MAX_RETRIES:
                time.sleep(RETRY_WAIT_SECONDS)

    if raw_keywords is None:
        raise RuntimeError(
            "키워드 추출이 "
            f"{MAX_RETRIES}회 모두 실패했습니다: {last_error}"
        )

    grounded_keywords = []

    for item in raw_keywords:
        matched_articles = [
            articles_by_id[article_id]
            for article_id in item["article_ids"]
            if article_id in articles_by_id
        ]

        # 코드 레벨 안전장치 1: 키워드에 3글자 이상 구체적인 토큰이
        # 하나도 없으면("영업 중단"처럼 2글자 일반 명사로만 구성된
        # 경우) 대조 자체가 무의미한 수준으로 느슨해지므로, 그 키워드
        # 자체를 통째로 버린다 — 애초에 프롬프트가 요구한 "구체적
        # 사건명"이 아니라는 뜻이다.
        keyword_tokens = keyword_search_tokens(item["keyword"])

        if not any(len(token) >= 3 for token in keyword_tokens):
            continue

        # 코드 레벨 안전장치 2: 키워드 핵심 토큰이 title/description
        # 어디에도 없는 기사는 Solar가 착각해서 끼워 넣은 것으로 보고
        # 여기서 제외한다 (LLM 재호출 없이 기계적으로 검증).
        grounded_articles = [
            article
            for article in matched_articles
            if article_matches_keyword_tokens(article, keyword_tokens)
        ]

        if not grounded_articles:
            continue

        grounded_keywords.append(
            {
                "keyword": item["keyword"],
                "summary": item["summary"],
                "article_ids": [
                    article["article_id"]
                    for article in grounded_articles
                ],
            }
        )

    # "3분기 대출 조임"/"가계대출 엄격 관리"처럼, 같은 사건을 가리키는
    # 키워드가 이름만 다르게 여러 개 나오는 경우가 있다(Q10에서 이벤트
    # 그룹에 쓴 것과 같은 현상). merge_overlapping_groups는 article_ids
    # 겹침 비율만 보고 병합하는 범용 함수라 키워드 딕셔너리에도 그대로
    # 재사용한다.
    merged_keywords = merge_overlapping_groups(grounded_keywords)

    scored_keywords = []

    for item in merged_keywords:
        merged_articles = [
            articles_by_id[article_id]
            for article_id in item["article_ids"]
            if article_id in articles_by_id
        ]

        publisher_ids = {
            article.get("publisher_id")
            for article in merged_articles
        }

        if len(publisher_ids) < KEYWORD_MIN_PUBLISHER_COUNT:
            continue

        scored_keywords.append(
            {
                "keyword": item["keyword"],
                "summary": item["summary"],
                "article_ids": item["article_ids"],
                "article_count": len(merged_articles),
                "publisher_count": len(publisher_ids),
            }
        )

    scored_keywords.sort(
        key=lambda item: (
            item["publisher_count"],
            item["article_count"],
        ),
        reverse=True,
    )

    return scored_keywords


def build_candidate_from_keyword(
    query: str,
    keyword_item: dict[str, Any],
    articles_by_id: dict[str, dict[str, Any]],
    n_publishers: int = DEFAULT_PUBLISHER_LIMIT,
) -> dict[str, Any] | None:
    """
    extract_query_keywords()가 반환한 키워드 하나를 비교 카드(candidate)로
    바로 조립한다. 새 검색이나 새 Event Grouping 호출 없이, 키워드
    추출 단계에서 이미 검증된 article_ids만 사용한다.
    """
    group_articles = [
        articles_by_id[article_id]
        for article_id in keyword_item["article_ids"]
        if article_id in articles_by_id
    ]

    representative_articles = select_representative_articles(
        group_articles,
        n_publishers=n_publishers,
    )

    if len(representative_articles) < 2:
        return None

    representative_article_ids = sorted(
        article["article_id"]
        for article in representative_articles
    )

    issue_id = "issue-" + hashlib.sha1(
        (
            f"{query.lower()}|"
            f"{keyword_item['keyword'].lower()}|"
            f"{','.join(representative_article_ids)}"
        ).encode("utf-8")
    ).hexdigest()[:16]

    candidate = {
        "issue_id": issue_id,
        "issue_title": keyword_item["keyword"],
        "summary": keyword_item.get("summary", ""),
        "query": query,
        "keyword": keyword_item["keyword"],
        "expanded_queries": [],
        "publishers": [
            {
                "publisher_id": article["publisher_id"],
                "publisher": article["publisher"],
                "articles": [article],
            }
            for article in representative_articles
        ],
    }

    return check_candidate_quality(candidate)
