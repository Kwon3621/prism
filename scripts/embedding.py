"""Upstage Passage Embedding 생성 모듈.

Article DB에서 읽은 기사 정보를 임베딩 가능한 텍스트로 변환하고,
Upstage embedding-passage 모델을 이용해 벡터를 생성한다.
"""

from __future__ import annotations

import os
from typing import Any, Iterable

from dotenv import load_dotenv
from openai import OpenAI


UPSTAGE_BASE_URL = "https://api.upstage.ai/v1"
PASSAGE_EMBEDDING_MODEL = "embedding-passage"
MAX_BATCH_SIZE = 100


def get_embedding_client() -> OpenAI:
    """환경변수에서 API 키를 읽어 Upstage 클라이언트를 생성한다."""
    load_dotenv()

    api_key = os.getenv("UPSTAGE_API_KEY")

    if not api_key:
        raise RuntimeError(
            "UPSTAGE_API_KEY가 설정되지 않았습니다. "
            "프로젝트 루트의 .env 파일을 확인하세요."
        )

    return OpenAI(
        api_key=api_key,
        base_url=UPSTAGE_BASE_URL,
    )


def build_article_text(article: dict[str, Any]) -> str:
    """기사 제목과 설명을 Passage Embedding 입력 텍스트로 변환한다."""
    title = str(article.get("title") or "").strip()
    description = str(article.get("description") or "").strip()

    if not title and not description:
        article_id = article.get("article_id", "알 수 없음")
        raise ValueError(
            f"기사 {article_id}에 title과 description이 모두 없습니다."
        )

    parts: list[str] = []

    if title:
        parts.append(f"제목: {title}")

    if description:
        parts.append(f"내용: {description}")

    return "\n".join(parts)


def _split_batches(
    items: list[str],
    batch_size: int,
) -> Iterable[list[str]]:
    """텍스트 목록을 지정된 크기의 배치로 나눈다."""
    if batch_size < 1 or batch_size > MAX_BATCH_SIZE:
        raise ValueError(
            f"batch_size는 1 이상 {MAX_BATCH_SIZE} 이하여야 합니다."
        )

    for start in range(0, len(items), batch_size):
        yield items[start : start + batch_size]


def create_passage_embeddings(
    texts: list[str],
    *,
    batch_size: int = MAX_BATCH_SIZE,
    client: OpenAI | None = None,
) -> list[list[float]]:
    """텍스트 목록을 Upstage Passage Embedding 벡터로 변환한다."""
    if not texts:
        return []

    normalized_texts = [text.strip() for text in texts]

    if any(not text for text in normalized_texts):
        raise ValueError("임베딩 입력에는 빈 문자열을 포함할 수 없습니다.")

    embedding_client = client or get_embedding_client()
    embeddings: list[list[float]] = []

    for batch in _split_batches(normalized_texts, batch_size):
        response = embedding_client.embeddings.create(
            model=PASSAGE_EMBEDDING_MODEL,
            input=batch,
        )

        ordered_data = sorted(
            response.data,
            key=lambda item: item.index,
        )

        embeddings.extend(
            item.embedding
            for item in ordered_data
        )

    if len(embeddings) != len(normalized_texts):
        raise RuntimeError(
            "요청한 텍스트 수와 반환된 임베딩 수가 일치하지 않습니다."
        )

    return embeddings


def embed_articles(
    articles: list[dict[str, Any]],
    *,
    batch_size: int = MAX_BATCH_SIZE,
) -> list[list[float]]:
    """기사 목록의 제목과 description을 Passage Embedding으로 변환한다."""
    texts = [build_article_text(article) for article in articles]

    return create_passage_embeddings(
        texts,
        batch_size=batch_size,
    )
