"""기사 임베딩을 로컬 파일(NumPy + JSON)에 저장하고 조회하는 모듈.

ChromaDB 대신 파일 기반으로 저장하는 이유:
Vercel Serverless Function 등은 요청마다 파일시스템이 초기화되어
로컬 영구 DB(ChromaDB PersistentClient)를 그대로 쓸 수 없다.
대신 임베딩을 data/vector_store/ 안의 정적 파일로 커밋해 배포하고,
서버리스 함수가 매 요청마다 이 파일을 메모리에 올려 코사인 유사도로
검색한다. 기사 수가 (60일 보관 정책상) 수천 개 수준이라 성능·용량
문제가 없다.

이 모듈이 노출하는 함수 시그니처는 기존 ChromaDB 버전과 동일하게
유지했다. index_articles.py, search_engine.py 등 호출부는
수정할 필요가 없다.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "vector_store"
DEFAULT_COLLECTION_NAME = "prism_articles"

EMBEDDINGS_FILENAME = "embeddings.npy"
RECORDS_FILENAME = "records.json"


class FileVectorCollection:
    """
    ChromaDB Collection과 유사한 최소 인터페이스(upsert/get/query/count)를
    제공하는 파일 기반 벡터 저장소.
    """

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.embeddings_path = db_path / EMBEDDINGS_FILENAME
        self.records_path = db_path / RECORDS_FILENAME

        self._ids: list[str] = []
        self._records: dict[str, dict[str, Any]] = {}
        self._embeddings: np.ndarray = np.zeros((0, 0), dtype="float32")

        self._load()

    def _load(self) -> None:
        if self.records_path.exists():
            with self.records_path.open("r", encoding="utf-8") as file:
                data = json.load(file)

            self._ids = list(data.get("ids", []))
            documents = data.get("documents", [])
            metadatas = data.get("metadatas", [])

            self._records = {
                article_id: {
                    "document": document,
                    "metadata": metadata,
                }
                for article_id, document, metadata in zip(
                    self._ids, documents, metadatas
                )
            }

        if self.embeddings_path.exists():
            self._embeddings = np.load(self.embeddings_path)

    def _save(self) -> None:
        self.db_path.mkdir(parents=True, exist_ok=True)

        np.save(self.embeddings_path, self._embeddings)

        with self.records_path.open("w", encoding="utf-8") as file:
            json.dump(
                {
                    "ids": self._ids,
                    "documents": [
                        self._records[article_id]["document"]
                        for article_id in self._ids
                    ],
                    "metadatas": [
                        self._records[article_id]["metadata"]
                        for article_id in self._ids
                    ],
                },
                file,
                ensure_ascii=False,
            )

    @staticmethod
    def _normalize(vectors: np.ndarray) -> np.ndarray:
        """코사인 유사도를 내적으로 계산할 수 있도록 벡터를 정규화한다."""
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return vectors / norms

    def upsert(
        self,
        ids: list[str],
        embeddings: list[list[float]],
        documents: list[str],
        metadatas: list[dict[str, str]],
    ) -> None:
        new_vectors = self._normalize(
            np.asarray(embeddings, dtype="float32")
        )

        for index, article_id in enumerate(ids):
            self._records[article_id] = {
                "document": documents[index],
                "metadata": metadatas[index],
            }

            if article_id in self._ids:
                row = self._ids.index(article_id)
                self._embeddings[row] = new_vectors[index]
            else:
                self._ids.append(article_id)
                if self._embeddings.shape[0] == 0:
                    self._embeddings = new_vectors[index : index + 1]
                else:
                    self._embeddings = np.vstack(
                        [self._embeddings, new_vectors[index]]
                    )

        self._save()

    def get(
        self,
        ids: list[str],
        include: list[str] | None = None,
    ) -> dict[str, Any]:
        found_ids: list[str] = []
        metadatas: list[dict[str, str]] = []

        for article_id in ids:
            record = self._records.get(article_id)
            if record is not None:
                found_ids.append(article_id)
                metadatas.append(record["metadata"])

        return {"ids": found_ids, "metadatas": metadatas}

    def count(self) -> int:
        return len(self._ids)

    def query(
        self,
        query_embeddings: list[list[float]],
        n_results: int,
        include: list[str] | None = None,
    ) -> dict[str, Any]:
        if not self._ids:
            return {
                "ids": [[]],
                "documents": [[]],
                "metadatas": [[]],
                "distances": [[]],
            }

        query_vector = np.asarray(
            query_embeddings[0], dtype="float32"
        )
        query_norm = np.linalg.norm(query_vector)
        if query_norm == 0:
            query_norm = 1.0
        query_vector = query_vector / query_norm

        # 두 벡터 모두 정규화되어 있으므로 내적 = 코사인 유사도
        similarities = self._embeddings @ query_vector
        distances = 1.0 - similarities

        top_n = min(n_results, len(self._ids))
        top_indices = np.argsort(distances)[:top_n]

        return {
            "ids": [[self._ids[i] for i in top_indices]],
            "documents": [
                [self._records[self._ids[i]]["document"] for i in top_indices]
            ],
            "metadatas": [
                [self._records[self._ids[i]]["metadata"] for i in top_indices]
            ],
            "distances": [[float(distances[i]) for i in top_indices]],
        }


def get_vector_collection(
    *,
    db_path: Path | str = DEFAULT_DB_PATH,
    collection_name: str = DEFAULT_COLLECTION_NAME,
) -> FileVectorCollection:
    """파일 기반 벡터 컬렉션을 반환한다. (collection_name은 호환성을 위해 유지, 미사용)"""
    return FileVectorCollection(Path(db_path))


def build_article_metadata(
    article: dict[str, Any],
) -> dict[str, str]:
    """기사 정보를 저장용 metadata 형식으로 변환한다."""
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
    저장된 document에서 기사 제목과 설명을 분리한다.

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
            title = normalized_line.removeprefix("제목:").strip()

        elif normalized_line.startswith("내용:"):
            description = normalized_line.removeprefix("내용:").strip()

    return title, description


def upsert_article_embeddings(
    articles: list[dict[str, Any]],
    embeddings: list[list[float]],
    documents: list[str],
    *,
    collection: FileVectorCollection | None = None,
) -> int:
    """기사 벡터를 article_id 기준으로 추가 또는 갱신한다."""
    if not articles:
        return 0

    if not (len(articles) == len(embeddings) == len(documents)):
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
            build_article_metadata(article) for article in articles
        ],
    )

    return len(article_ids)


def search_article_embeddings(
    query_embedding: list[float],
    *,
    n_results: int = 50,
    collection: FileVectorCollection | None = None,
) -> list[dict[str, Any]]:
    """
    검색어 임베딩과 유사한 기사를 조회한다.

    반환 기사에는 article_id, title, description, publisher 정보와
    similarity_score가 포함된다.
    """
    if not isinstance(query_embedding, list):
        raise ValueError("query_embedding은 숫자 배열이어야 합니다.")

    if not query_embedding:
        raise ValueError("query_embedding이 비어 있습니다.")

    if n_results < 1:
        raise ValueError("n_results는 1 이상이어야 합니다.")

    target_collection = collection or get_vector_collection()

    stored_count = target_collection.count()

    if stored_count == 0:
        return []

    actual_result_count = min(n_results, stored_count)

    query_result = target_collection.query(
        query_embeddings=[query_embedding],
        n_results=actual_result_count,
        include=["documents", "metadatas", "distances"],
    )

    ids = (query_result.get("ids") or [[]])[0]
    documents = (query_result.get("documents") or [[]])[0]
    metadatas = (query_result.get("metadatas") or [[]])[0]
    distances = (query_result.get("distances") or [[]])[0]

    articles: list[dict[str, Any]] = []

    for article_id, document, metadata, distance in zip(
        ids, documents, metadatas, distances
    ):
        metadata = metadata or {}

        title, description = parse_article_document(document or "")

        numeric_distance = float(distance)

        # cosine distance는 작을수록 유사하다.
        # similarity_score는 클수록 유사하도록 변환한다.
        similarity_score = max(0.0, min(1.0, 1.0 - numeric_distance))

        articles.append(
            {
                "article_id": str(article_id),
                "publisher_id": str(metadata.get("publisher_id") or ""),
                "publisher": str(metadata.get("publisher") or ""),
                "category": str(metadata.get("category") or ""),
                "title": title,
                "description": description,
                "content": description,
                "published_at": str(metadata.get("published_at") or ""),
                "updated_at": str(metadata.get("updated_at") or ""),
                "link": str(metadata.get("link") or ""),
                "distance": round(numeric_distance, 6),
                "similarity_score": round(similarity_score, 6),
            }
        )

    return articles


def get_stored_updated_at(
    article_ids: list[str],
    *,
    collection: FileVectorCollection | None = None,
) -> dict[str, str]:
    """저장된 기사별 updated_at 값을 반환한다."""
    if not article_ids:
        return {}

    target_collection = collection or get_vector_collection()

    result = target_collection.get(ids=article_ids, include=["metadatas"])

    stored_values: dict[str, str] = {}

    for article_id, metadata in zip(
        result.get("ids", []), result.get("metadatas", []) or []
    ):
        stored_values[str(article_id)] = str(
            (metadata or {}).get("updated_at") or ""
        )

    return stored_values


def count_stored_articles(
    *,
    collection: FileVectorCollection | None = None,
) -> int:
    """현재 Vector Store에 저장된 기사 수를 반환한다."""
    target_collection = collection or get_vector_collection()

    return target_collection.count()