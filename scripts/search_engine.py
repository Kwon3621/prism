"""
검색어 확장, ChromaDB 벡터 검색, 검색 결과 랭킹을 담당하는 모듈.
"""

from __future__ import annotations

import os
from typing import Any

import requests
from dotenv import load_dotenv

from query_embedding import embed_query
from ranking import calculate_score
from vector_store import search_article_embeddings


load_dotenv()

UPSTAGE_API_KEY = os.getenv("UPSTAGE_API_KEY")
UPSTAGE_CHAT_URL = (
    "https://api.upstage.ai/v1/chat/completions"
)

DEFAULT_VECTOR_RESULT_COUNT = 50


FALLBACK_QUERY_EXPANSION = {
    "금리": [
        "기준금리",
        "한국은행",
        "통화정책",
    ],
    "반도체": [
        "메모리",
        "DRAM",
        "HBM",
        "AI 반도체",
    ],
    "주식": [
        "증시",
        "코스피",
        "코스닥",
    ],
    "대통령": [
        "정부",
        "대통령실",
    ],
}


def clean_query_terms(
    terms: list[str],
) -> list[str]:
    """검색어 목록의 공백과 중복을 제거한다."""
    cleaned_terms: list[str] = []
    seen: set[str] = set()

    for term in terms:
        normalized_term = str(
            term or ""
        ).strip()

        if not normalized_term:
            continue

        normalized_key = normalized_term.lower()

        if normalized_key in seen:
            continue

        seen.add(normalized_key)
        cleaned_terms.append(normalized_term)

    return cleaned_terms


def expand_query_with_solar(
    query: str,
) -> list[str] | None:
    """
    Solar LLM으로 검색어의 의미를 확장한다.

    API 키가 없거나 호출에 실패하면 None을 반환한다.
    """
    if not UPSTAGE_API_KEY:
        return None

    prompt = (
        f"사용자가 뉴스 검색창에 '{query}'라고 입력했습니다. "
        "이 검색어와 의미적으로 관련된 한국어 뉴스 검색어를 "
        "3개에서 5개 제안하세요. "
        "원래 검색어는 제외하세요. "
        "쉼표로 구분된 검색어 목록만 출력하세요."
    )

    try:
        response = requests.post(
            UPSTAGE_CHAT_URL,
            headers={
                "Authorization": (
                    f"Bearer {UPSTAGE_API_KEY}"
                ),
                "Content-Type": "application/json",
            },
            json={
                "model": "solar-pro",
                "messages": [
                    {
                        "role": "user",
                        "content": prompt,
                    }
                ],
            },
            timeout=15,
        )

        response.raise_for_status()

        content = response.json()[
            "choices"
        ][0]["message"]["content"]

        terms = [
            term.strip()
            for term in content.split(",")
            if term.strip()
        ]

        return clean_query_terms(terms)

    except (
        requests.RequestException,
        KeyError,
        IndexError,
        TypeError,
    ) as error:
        print(
            "Solar 확장 검색어 생성에 실패했습니다. "
            f"대체 검색어를 사용합니다: {error}"
        )
        return None


def expand_query(
    query: str,
) -> list[str]:
    """
    검색어를 확장한다.

    우선순위:
    1. 원래 검색어
    2. Solar LLM 확장어
    3. Solar 실패 시 하드코딩 대체어
    """
    normalized_query = str(
        query or ""
    ).strip()

    if not normalized_query:
        raise ValueError(
            "검색어가 비어 있습니다."
        )

    expanded_queries = [
        normalized_query
    ]

    solar_terms = expand_query_with_solar(
        normalized_query
    )

    if solar_terms:
        expanded_queries.extend(
            solar_terms
        )

    elif normalized_query in (
        FALLBACK_QUERY_EXPANSION
    ):
        expanded_queries.extend(
            FALLBACK_QUERY_EXPANSION[
                normalized_query
            ]
        )

    return clean_query_terms(
        expanded_queries
    )


def merge_search_result(
    stored_result: dict[str, Any] | None,
    new_result: dict[str, Any],
) -> dict[str, Any]:
    """
    같은 기사가 여러 확장 검색어에서 조회된 경우
    가장 높은 의미 유사도 결과를 유지한다.
    """
    if stored_result is None:
        return new_result.copy()

    stored_similarity = float(
        stored_result.get(
            "similarity_score"
        )
        or 0.0
    )

    new_similarity = float(
        new_result.get(
            "similarity_score"
        )
        or 0.0
    )

    if new_similarity > stored_similarity:
        return new_result.copy()

    return stored_result


def semantic_search(
    queries: list[str],
    *,
    n_results_per_query: int = (
        DEFAULT_VECTOR_RESULT_COUNT
    ),
) -> list[dict[str, Any]]:
    """
    확장 검색어별로 Query Embedding을 생성하고
    ChromaDB에서 의미적으로 유사한 기사를 검색한다.
    """
    if not queries:
        return []

    if n_results_per_query < 1:
        raise ValueError(
            "n_results_per_query는 "
            "1 이상이어야 합니다."
        )

    results_by_article_id: dict[
        str,
        dict[str, Any],
    ] = {}

    for query in queries:
        query_embedding = embed_query(
            query
        )

        if not query_embedding:
            print(
                f"검색어 임베딩 생성 실패: {query}"
            )
            continue

        query_results = (
            search_article_embeddings(
                query_embedding,
                n_results=(
                    n_results_per_query
                ),
            )
        )

        for article in query_results:
            article_id = str(
                article.get(
                    "article_id"
                )
                or ""
            ).strip()

            if not article_id:
                continue

            article_with_match = {
                **article,
                "matched_query": query,
            }

            results_by_article_id[
                article_id
            ] = merge_search_result(
                results_by_article_id.get(
                    article_id
                ),
                article_with_match,
            )

    return list(
        results_by_article_id.values()
    )


def rank_results(
    results: list[dict[str, Any]],
    original_query: str,
    queries: list[str] | None = None,
) -> list[dict[str, Any]]:
    """
    의미 유사도, 키워드 일치도, 최신성을 반영해
    검색 결과를 정렬한다.
    """
    ranking_queries = (
        queries
        or [original_query]
    )

    scored_results = [
        {
            **article,
            "score": calculate_score(
                article,
                original_query,
                ranking_queries,
            ),
        }
        for article in results
    ]

    return sorted(
        scored_results,
        key=lambda article: (
            float(
                article.get("score")
                or 0.0
            ),
            float(
                article.get(
                    "similarity_score"
                )
                or 0.0
            ),
        ),
        reverse=True,
    )


def search_with_context(
    query: str,
    *,
    n_results_per_query: int = (
        DEFAULT_VECTOR_RESULT_COUNT
    ),
) -> dict[str, Any]:
    """
    검색 결과와 실제 사용된 확장 검색어를 함께 반환한다.

    검색어 확장을 한 번만 실행하므로,
    후속 대표 기사 선택과 분석 입력 생성에서
    동일한 expanded_queries를 재사용할 수 있다.
    """
    expanded_queries = expand_query(
        query
    )

    results = semantic_search(
        expanded_queries,
        n_results_per_query=(
            n_results_per_query
        ),
    )

    ranked_results = rank_results(
        results,
        query,
        expanded_queries,
    )

    return {
        "query": query,
        "expanded_queries": expanded_queries,
        "results": ranked_results,
    }

def search(
    query: str,
    *,
    n_results_per_query: int = (
        DEFAULT_VECTOR_RESULT_COUNT
    ),
) -> list[dict[str, Any]]:
    """
    기존 호출부와의 호환성을 유지하며
    정렬된 기사 목록만 반환한다.
    """
    search_context = search_with_context(
        query,
        n_results_per_query=(
            n_results_per_query
        ),
    )

    return search_context["results"]


def main() -> None:
    query = "기준금리"

    results = search(
        query,
        n_results_per_query=10,
    )

    print(
        f"검색어: {query}"
    )
    print(
        f"검색 결과 수: {len(results)}"
    )

    for index, article in enumerate(
        results[:10],
        start=1,
    ):
        print(
            "{}. [{}] {} | "
            "점수={} | 유사도={}".format(
                index,
                article.get(
                    "publisher",
                    "",
                ),
                article.get(
                    "title",
                    "",
                ),
                article.get(
                    "score",
                    "",
                ),
                article.get(
                    "similarity_score",
                    "",
                ),
            )
        )


if __name__ == "__main__":
    main()