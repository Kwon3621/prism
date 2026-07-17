"""기사 임베딩을 ChromaDB에 저장하고 조회하는 모듈."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import chromadb
from chromadb.api.models.Collection import Collection


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "vector_db"
DEFAULT_COLLECTION_NAME = "prism_articles"


def get_vector_collection(
    *,
    db_path: Path | str = DEFAULT_DB_PATH,
    collection_name: str = DEFAULT_COLLECTION_NAME,
) -> Collection:
    """로컬 영구 ChromaDB 컬렉션을 반환한다."""
    resolved_path = Path(db_path)
    resolved_path.mkdir(parents=True, exist_ok=True)

    client = chromadb.PersistentClient(
        path=str(resolved_path),
    )

    return client.get_or_create_collection(
        name=collection_name,
        configuration={
            "hnsw": {
                "space": "cosine",
            }
        },
    )


def build_article_metadata(article: dict[str, Any]) -> dict[str, str]:
    """기사 정보를 ChromaDB metadata 형식으로 변환한다."""
    metadata_fields = (
        "publisher_id",
        "publisher",
        "category",
        "published_at",
        "updated_at",
        "link",
    )

    return {
        field: str(article.get(field) or "")
        for field in metadata_fields
    }


def upsert_article_embeddings(
    articles: list[dict[str, Any]],
    embeddings: list[list[float]],
    documents: list[str],
    *,
    collection: Collection | None = None,
) -> int:
    """기사 벡터를 article_id 기준으로 추가 또는 갱신한다."""
    if not articles:
        return 0

    if not (
        len(articles) == len(embeddings) == len(documents)
    ):
        raise ValueError(
            "articles, embeddings, documents의 개수가 일치해야 합니다."
        )

    article_ids: list[str] = []

    for article in articles:
        article_id = str(article.get("article_id") or "").strip()

        if not article_id:
            raise ValueError("모든 기사에 article_id가 있어야 합니다.")

        article_ids.append(article_id)

    target_collection = collection or get_vector_collection()

    target_collection.upsert(
        ids=article_ids,
        embeddings=embeddings,
        documents=documents,
        metadatas=[
            build_article_metadata(article)
            for article in articles
        ],
    )

    return len(article_ids)


def get_stored_updated_at(
    article_ids: list[str],
    *,
    collection: Collection | None = None,
) -> dict[str, str]:
    """저장된 기사별 updated_at 값을 반환한다."""
    if not article_ids:
        return {}

    target_collection = collection or get_vector_collection()

    result = target_collection.get(
        ids=article_ids,
        include=["metadatas"],
    )

    stored_values: dict[str, str] = {}

    for article_id, metadata in zip(
        result.get("ids", []),
        result.get("metadatas", []) or [],
    ):
        stored_values[str(article_id)] = str(
            (metadata or {}).get("updated_at") or ""
        )

    return stored_values


def count_stored_articles(
    *,
    collection: Collection | None = None,
) -> int:
    """현재 Vector DB에 저장된 기사 수를 반환한다."""
    target_collection = collection or get_vector_collection()
    return target_collection.count()
