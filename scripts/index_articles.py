"""Article DB에서 신규·변경 기사를 찾아 Vector DB에 반영하는 실행 스크립트."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from generate_news import migrate_existing_article

from embedding import build_article_text, embed_articles
from vector_store import (
    count_stored_articles,
    get_stored_updated_at,
    get_vector_collection,
    upsert_article_embeddings,
    delete_article_embeddings,
    list_stored_article_ids,
)


REQUIRED_FIELDS = (
    "article_id",
    "publisher_id",
    "publisher",
    "category",
    "title",
    "description",
    "published_at",
    "updated_at",
    "link",
)


def load_articles(source_path: Path) -> list[dict[str, Any]]:
    """JSON 파일에서 기사를 읽고 현재 Article DB 스키마로 변환한다."""
    if not source_path.exists():
        raise FileNotFoundError(
            f"Article DB 파일을 찾을 수 없습니다: {source_path}"
        )

    with source_path.open("r", encoding="utf-8-sig") as file:
        data = json.load(file)

    if not isinstance(data, list):
        raise ValueError(
            "Article DB JSON의 최상위 구조는 배열이어야 합니다."
        )

    current_time = datetime.now(
        timezone.utc
    ).isoformat()

    articles: list[dict[str, Any]] = []

    for index, item in enumerate(data, start=1):
        migrated_item = migrate_existing_article(
            item,
            current_time,
        )

        if not isinstance(migrated_item, dict):
            raise ValueError(
                f"{index}번째 기사 데이터가 객체 형식이 아닙니다."
            )

        missing_fields = [
            field
            for field in REQUIRED_FIELDS
            if field not in migrated_item
        ]

        if missing_fields:
            raise ValueError(
                f"{index}번째 기사에 필수 필드가 없습니다: "
                f"{', '.join(missing_fields)}"
            )

        required_nonempty_fields = (
            "article_id",
            "publisher_id",
            "publisher",
            "title",
            "link",
        )

        empty_fields = [
            field
            for field in required_nonempty_fields
            if not str(
                migrated_item.get(field) or ""
            ).strip()
        ]

        if empty_fields:
            raise ValueError(
                f"{index}번째 기사의 필수 값이 비어 있습니다: "
                f"{', '.join(empty_fields)}"
            )

        articles.append(migrated_item)

    return articles


def select_articles_to_index(
    articles: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """신규 기사와 updated_at이 변경된 기사만 선택한다."""
    article_ids = [
        str(article["article_id"]).strip()
        for article in articles
    ]

    stored_updated_at = get_stored_updated_at(article_ids)

    selected: list[dict[str, Any]] = []

    for article in articles:
        article_id = str(article["article_id"]).strip()
        current_updated_at = str(
            article.get("updated_at") or ""
        ).strip()

        previous_updated_at = stored_updated_at.get(article_id)

        if previous_updated_at is None:
            selected.append(article)
            continue

        if current_updated_at != previous_updated_at:
            selected.append(article)

    return selected

def delete_stale_embeddings(
    articles: list[dict[str, Any]],
) -> int:
    """Article DB에 없는 오래된 벡터를 Vector Store에서 삭제한다."""
    current_article_ids = {
        str(article["article_id"]).strip()
        for article in articles
        if str(article.get("article_id") or "").strip()
    }

    stored_article_ids = set(
        list_stored_article_ids()
    )

    stale_article_ids = sorted(
        stored_article_ids - current_article_ids
    )

    deleted_count = delete_article_embeddings(
        stale_article_ids
    )

    return deleted_count

def index_articles(source_path: Path) -> int:
    """Article DB와 Vector Store를 동기화하고 신규·변경 기사를 저장한다."""
    articles = load_articles(source_path)

    deleted_count = delete_stale_embeddings(articles)
    target_articles = select_articles_to_index(articles)

    print(f"전체 기사 수: {len(articles)}")
    print(f"삭제된 오래된 벡터 수: {deleted_count}")
    print(f"임베딩 대상 기사 수: {len(target_articles)}")

    if not target_articles:
        print("신규 또는 변경된 기사가 없습니다.")
        print(f"Vector DB 저장 기사 수: {count_stored_articles()}")
        return 0

    documents = [
        build_article_text(article)
        for article in target_articles
    ]

    embeddings = embed_articles(target_articles)

    collection = get_vector_collection()

    indexed_count = upsert_article_embeddings(
        target_articles,
        embeddings,
        documents,
        collection=collection,
    )

    print(f"Vector DB 반영 완료: {indexed_count}개")
    print(f"Vector DB 전체 기사 수: {collection.count()}")

    return indexed_count


def parse_args() -> argparse.Namespace:
    """명령행 인자를 읽는다."""
    parser = argparse.ArgumentParser(
        description=(
            "Article DB의 신규·변경 기사를 Upstage로 임베딩한 뒤 "
            "ChromaDB에 저장합니다."
        )
    )

    parser.add_argument(
        "--source",
        type=Path,
        required=True,
        help="A팀 Article DB JSON 파일 경로",
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()
    index_articles(args.source)


if __name__ == "__main__":
    main()
