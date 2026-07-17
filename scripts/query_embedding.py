"""
Query Embedding

검색어를 임베딩 벡터로 변환한다. (Upstage Solar Embedding API 사용)

A팀의 Vector DB 작업이 끝나면, 여기서 만든 벡터를 A팀 vector_db.py의
검색 함수에 넘겨서 실제 semantic_search에 연결할 예정.
지금은 이 모듈만 독립적으로 정상 동작하는지 확인한다.
"""
import os

import requests
from dotenv import load_dotenv

load_dotenv()

UPSTAGE_API_KEY = os.getenv("UPSTAGE_API_KEY")
UPSTAGE_EMBEDDING_URL = "https://api.upstage.ai/v1/embeddings"

# 검색어(query) 전용 임베딩 모델명
QUERY_EMBEDDING_MODEL = "embedding-query"


def embed_query(query):
    """
    검색어를 임베딩 벡터(리스트)로 변환한다.
    실패하면 None을 반환한다.
    """
    if not UPSTAGE_API_KEY:
        print("UPSTAGE_API_KEY가 설정되지 않았습니다. .env 파일을 확인하세요.")
        return None

    try:
        response = requests.post(
            UPSTAGE_EMBEDDING_URL,
            headers={
                "Authorization": f"Bearer {UPSTAGE_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": QUERY_EMBEDDING_MODEL,
                "input": query,
            },
            timeout=15,
        )
        response.raise_for_status()

        return response.json()["data"][0]["embedding"]

    except (requests.RequestException, KeyError, IndexError) as error:
        print(f"쿼리 임베딩 실패: {error}")
        return None


if __name__ == "__main__":
    test_query = "금리"
    vector = embed_query(test_query)

    if vector:
        print(f"'{test_query}' 임베딩 벡터 차원: {len(vector)}")
        print(f"앞부분 5개 값: {vector[:5]}")
    else:
        print("임베딩 생성 실패 - API 키 또는 모델명을 확인하세요.")