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


def build_article_metadata(
    article: dict[str, Any],
) -> dict[str, str]:
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


def parse_article_document(
    document: str,
) -> tuple[str, str]:
    """
    ChromaDB document에서 기사 제목과 설명을 분리한다.

    저장 형식:
    제목: 기사 제목
    내용: 기사 설명
    """
    title = ""
    description = ""

    if not isinstance(document, str):
        return title, description

    for line in document.splitlines():
        normalized_line = line.strip()

        if normalized_line.startswith("제목:"):
            title = normalized_line.removeprefix(
                "제목:"
            ).strip()

        elif normalized_line.startswith("내용:"):
            description = normalized_line.removeprefix(
                "내용:"
            ).strip()

    return title, description


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
        len(articles)
        == len(embeddings)
        == len(documents)
    ):
        raise ValueError(
            "articles, embeddings, documents의 "
            "개수가 일치해야 합니다."
        )

    article_ids: list[str] = []

    for article in articles:
        article_id = str(
            article.get("article_id") or ""
        ).strip()

        if not article_id:
            raise ValueError(
                "모든 기사에 article_id가 있어야 합니다."
            )

        article_ids.append(article_id)

    target_collection = (
        collection
        or get_vector_collection()
    )

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


def search_article_embeddings(
    query_embedding: list[float],
    *,
    n_results: int = 50,
    collection: Collection | None = None,
) -> list[dict[str, Any]]:
    """
    검색어 임베딩과 유사한 기사를 ChromaDB에서 조회한다.

    반환 기사에는 C파트에서 필요한 article_id, title,
    description, publisher 정보와 similarity_score가 포함된다.
    """
    if not isinstance(query_embedding, list):
        raise ValueError(
            "query_embedding은 숫자 배열이어야 합니다."
        )

    if not query_embedding:
        raise ValueError(
            "query_embedding이 비어 있습니다."
        )

    if n_results < 1:
        raise ValueError(
            "n_results는 1 이상이어야 합니다."
        )

    target_collection = (
        collection
        or get_vector_collection()
    )

    stored_count = target_collection.count()

    if stored_count == 0:
        return []

    actual_result_count = min(
        n_results,
        stored_count,
    )

    query_result = target_collection.query(
        query_embeddings=[
            query_embedding
        ],
        n_results=actual_result_count,
        include=[
            "documents",
            "metadatas",
            "distances",
        ],
    )

    ids = (
        query_result.get("ids")
        or [[]]
    )[0]

    documents = (
        query_result.get("documents")
        or [[]]
    )[0]

    metadatas = (
        query_result.get("metadatas")
        or [[]]
    )[0]

    distances = (
        query_result.get("distances")
        or [[]]
    )[0]

    articles: list[dict[str, Any]] = []

    for (
        article_id,
        document,
        metadata,
        distance,
    ) in zip(
        ids,
        documents,
        metadatas,
        distances,
    ):
        metadata = metadata or {}

        title, description = (
            parse_article_document(
                document or ""
            )
        )

        numeric_distance = float(distance)

        # cosine distance는 작을수록 유사하다.
        # similarity_score는 클수록 유사하도록 변환한다.
        similarity_score = max(
            0.0,
            min(
                1.0,
                1.0 - numeric_distance,
            ),
        )

        articles.append(
            {
                "article_id": str(
                    article_id
                ),
                "publisher_id": str(
                    metadata.get(
                        "publisher_id"
                    )
                    or ""
                ),
                "publisher": str(
                    metadata.get(
                        "publisher"
                    )
                    or ""
                ),
                "category": str(
                    metadata.get(
                        "category"
                    )
                    or ""
                ),
                "title": title,
                "description": description,
                "content": description,
                "published_at": str(
                    metadata.get(
                        "published_at"
                    )
                    or ""
                ),
                "updated_at": str(
                    metadata.get(
                        "updated_at"
                    )
                    or ""
                ),
                "link": str(
                    metadata.get(
                        "link"
                    )
                    or ""
                ),
                "distance": round(
                    numeric_distance,
                    6,
                ),
                "similarity_score": round(
                    similarity_score,
                    6,
                ),
            }
        )

    return articles


def get_stored_updated_at(
    article_ids: list[str],
    *,
    collection: Collection | None = None,
) -> dict[str, str]:
    """저장된 기사별 updated_at 값을 반환한다."""
    if not article_ids:
        return {}

    target_collection = (
        collection
        or get_vector_collection()
    )

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
            (metadata or {}).get(
                "updated_at"
            )
            or ""
        )

    return stored_values


def count_stored_articles(
    *,
    collection: Collection | None = None,
) -> int:
    """현재 Vector DB에 저장된 기사 수를 반환한다."""
    target_collection = (
        collection
        or get_vector_collection()
    )

    return target_collection.count()