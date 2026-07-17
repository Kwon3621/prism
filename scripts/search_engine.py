"""
Search Engine

B팀 검색 파이프라인

1. Query Expansion (Solar LLM 기반, 실패 시 폴백 사전 사용)
2. Semantic Search (임시: 텍스트 매칭 / 추후 A팀 Vector DB로 교체)
3. Search Result Ranking (ranking.py의 calculate_score 사용)
"""
import os

import requests
from dotenv import load_dotenv

from ranking import calculate_score

load_dotenv()

UPSTAGE_API_KEY = os.getenv("UPSTAGE_API_KEY")
UPSTAGE_CHAT_URL = "https://api.upstage.ai/v1/chat/completions"

# Solar 호출이 실패했을 때 쓰는 폴백 사전
FALLBACK_QUERY_EXPANSION = {
    "금리": ["기준금리", "한국은행", "통화정책"],
    "반도체": ["메모리", "DRAM", "HBM", "AI 반도체"],
    "주식": ["증시", "코스피", "코스닥"],
    "대통령": ["정부", "대통령실"],
}

# 테스트용 기사 데이터
SAMPLE_ARTICLES = [
    {
        "title": "한국은행 기준금리 동결",
        "publisher": "한국경제",
        "content": "한국은행 금융통화위원회가 기준금리를 동결했다.",
        "published_at": "2026-07-17T09:00:00+00:00",
    },
    {
        "title": "반도체 수출 증가",
        "publisher": "매일경제",
        "content": "HBM과 DRAM 수요 증가로 반도체 수출이 늘었다.",
        "published_at": "2026-07-16T09:00:00+00:00",
    },
    {
        "title": "코스피 상승 마감",
        "publisher": "조선일보",
        "content": "외국인 매수세에 코스피가 상승했다.",
        "published_at": "2026-07-15T09:00:00+00:00",
    },
]


def expand_query_with_solar(query):
    """
    Solar LLM으로 검색어의 의도를 확장한다.
    API 키가 없거나 호출이 실패하면 None을 반환한다.
    """
    if not UPSTAGE_API_KEY:
        return None

    prompt = (
        f"사용자가 뉴스 검색창에 '{query}'라고 입력했다. "
        "이 검색어와 의미적으로 관련된 확장 검색어를 3~5개 제안해줘. "
        "응답은 쉼표로 구분된 단어 목록만 출력하고 다른 설명은 하지 마."
    )

    try:
        response = requests.post(
            UPSTAGE_CHAT_URL,
            headers={
                "Authorization": f"Bearer {UPSTAGE_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": "solar-pro",
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=15,
        )
        response.raise_for_status()

        content = response.json()["choices"][0]["message"]["content"]

        return [term.strip() for term in content.split(",") if term.strip()]

    except (requests.RequestException, KeyError, IndexError) as error:
        print(f"Solar 확장 검색어 생성 실패, 폴백 사전을 사용합니다: {error}")
        return None


def expand_query(query):
    """
    검색어 확장
    1순위: Solar LLM
    2순위: 하드코딩된 폴백 사전
    """
    expanded = [query]

    solar_terms = expand_query_with_solar(query)

    if solar_terms:
        expanded.extend(solar_terms)
    elif query in FALLBACK_QUERY_EXPANSION:
        expanded.extend(FALLBACK_QUERY_EXPANSION[query])

    return expanded


def semantic_search(queries):
    """
    임시 의미 검색
    (나중에 Vector DB 검색으로 교체 - A팀 작업 완료 후 연결)
    """
    results = []

    for article in SAMPLE_ARTICLES:
        text = (article["title"] + " " + article["content"]).lower()

        for query in queries:
            if query.lower() in text:
                results.append(article)
                break

    return results


def rank_results(results, original_query):
    """
    검색 결과를 calculate_score 기준으로 정렬한다.
    """
    scored_results = [
        {**article, "score": calculate_score(article, original_query)}
        for article in results
    ]

    return sorted(scored_results, key=lambda a: a["score"], reverse=True)


def search(query):
    """
    전체 검색 파이프라인
    """
    expanded_queries = expand_query(query)
    results = semantic_search(expanded_queries)
    ranked_results = rank_results(results, query)

    return ranked_results


if __name__ == "__main__":
    results = search("금리")

    print("검색 결과")

    for article in results:
        print(f"- {article['title']} ({article['publisher']}) 점수: {article['score']}")