#같은 이슈·언론사·기사 조합이면 동일한 캐시 키 생성
#언론사별 분석 결과 저장 및 조회
#선택 언론사 비교 결과 저장 및 조회
#캐시 폴더 자동 생성
#손상된 JSON 캐시는 오류를 내지 않고 무시

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# Vercel 서버리스 함수는 배포 번들 디렉터리가 읽기 전용이라 data/cache에
# 쓸 수 없고, /tmp(=tempfile.gettempdir())만 쓰기 가능하다.
# 로컬 개발 환경에서는 기존처럼 프로젝트 폴더 아래 data/cache를 사용한다.
if os.environ.get("VERCEL"):
    CACHE_ROOT = Path(tempfile.gettempdir()) / "prism-cache"
else:
    CACHE_ROOT = Path("data/cache")

PUBLISHER_CACHE_DIR = CACHE_ROOT / "publisher_analysis"
COMPARISON_CACHE_DIR = CACHE_ROOT / "comparisons"
KEYWORD_EXTRACTION_CACHE_DIR = CACHE_ROOT / "keyword_extraction"

# analysis.py/compare.py의 Solar 프롬프트나 검증 로직을 바꾸면 이 값을
# 올린다. 캐시 키에 포함시켜서, 예전 프롬프트로 만들어진 결과가 새 로직
# 적용 후에도 그대로 재사용되는 것을 막는다.
PROMPT_VERSION = "2026-07-21-tone-only-evidence"

# issue_builder.py의 키워드 추출 프롬프트/검증 로직을 바꾸면 이 값을
# 올린다. 위 PROMPT_VERSION과 분리한 이유는 서로 다른 프롬프트라 한쪽만
# 바뀌어도 다른 쪽 캐시까지 전부 무효화되는 걸 피하기 위해서다.
KEYWORD_EXTRACTION_PROMPT_VERSION = "2026-07-21-positional-index-desc150"


def ensure_cache_directories() -> None:
    """
    캐시 저장 폴더가 없으면 생성한다.
    """
    PUBLISHER_CACHE_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    COMPARISON_CACHE_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    KEYWORD_EXTRACTION_CACHE_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )


def make_cache_key(*parts: Any) -> str:
    """
    여러 값을 하나의 안정적인 캐시 키로 변환한다.

    리스트와 딕셔너리는 정렬된 JSON 문자열로 변환하기 때문에
    같은 입력이면 항상 같은 키가 생성된다.
    """
    normalized_parts = []

    for part in parts:
        if isinstance(part, (dict, list, tuple, set)):
            normalized = json.dumps(
                part,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            )
        else:
            normalized = str(part)

        normalized_parts.append(normalized)

    raw_key = "||".join(normalized_parts)

    return hashlib.sha256(
        raw_key.encode("utf-8")
    ).hexdigest()


def make_publisher_cache_key(
    issue_id: str,
    publisher_id: str,
    article_ids: list[str],
) -> str:
    """
    언론사별 분석 결과의 캐시 키를 만든다.
    기사 순서가 달라도 같은 기사 조합이면 같은 키를 반환한다.
    """
    return make_cache_key(
        "publisher-analysis",
        PROMPT_VERSION,
        issue_id,
        publisher_id,
        sorted(article_ids),
    )


def make_comparison_cache_key(
    issue_id: str,
    publisher_ids: list[str],
) -> str:
    """
    선택 언론사 비교 결과의 캐시 키를 만든다.
    언론사 선택 순서가 달라도 같은 조합이면 같은 키를 반환한다.
    """
    return make_cache_key(
        "publisher-comparison",
        PROMPT_VERSION,
        issue_id,
        sorted(publisher_ids),
    )


def _read_cache_file(path: Path) -> dict | None:
    """
    캐시 JSON 파일을 읽는다.
    파일이 없거나 손상되었으면 None을 반환한다.
    """
    if not path.exists():
        return None

    try:
        with path.open(
            "r",
            encoding="utf-8",
        ) as file:
            data = json.load(file)

        if not isinstance(data, dict):
            return None

        return data

    except (
        json.JSONDecodeError,
        OSError,
    ):
        return None


def _write_cache_file(
    path: Path,
    data: dict,
) -> None:
    """
    캐시 데이터를 UTF-8 JSON 파일로 저장한다.
    """
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with path.open(
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            data,
            file,
            ensure_ascii=False,
            indent=2,
        )


def get_publisher_analysis(
    issue_id: str,
    publisher_id: str,
    article_ids: list[str],
) -> dict | None:
    """
    저장된 언론사별 분석 결과를 조회한다.
    """
    ensure_cache_directories()

    cache_key = make_publisher_cache_key(
        issue_id,
        publisher_id,
        article_ids,
    )

    cache_path = (
        PUBLISHER_CACHE_DIR
        / f"{cache_key}.json"
    )

    cached_data = _read_cache_file(
        cache_path
    )

    if not cached_data:
        return None

    result = cached_data.get("result")

    if not isinstance(result, dict):
        return None

    return result


def save_publisher_analysis(
    issue_id: str,
    publisher_id: str,
    article_ids: list[str],
    result: dict,
) -> Path:
    """
    언론사별 Solar 분석 결과를 캐시에 저장한다.
    """
    ensure_cache_directories()

    cache_key = make_publisher_cache_key(
        issue_id,
        publisher_id,
        article_ids,
    )

    cache_path = (
        PUBLISHER_CACHE_DIR
        / f"{cache_key}.json"
    )

    cache_data = {
        "cache_type": "publisher_analysis",
        "cache_key": cache_key,
        "issue_id": issue_id,
        "publisher_id": publisher_id,
        "article_ids": sorted(article_ids),
        "created_at": datetime.now(
            timezone.utc
        ).isoformat(),
        "result": result,
    }

    _write_cache_file(
        cache_path,
        cache_data,
    )

    return cache_path


def get_comparison(
    issue_id: str,
    publisher_ids: list[str],
) -> dict | None:
    """
    저장된 선택 언론사 비교 결과를 조회한다.
    """
    ensure_cache_directories()

    cache_key = make_comparison_cache_key(
        issue_id,
        publisher_ids,
    )

    cache_path = (
        COMPARISON_CACHE_DIR
        / f"{cache_key}.json"
    )

    cached_data = _read_cache_file(
        cache_path
    )

    if not cached_data:
        return None

    result = cached_data.get("result")

    if not isinstance(result, dict):
        return None

    return result


def save_comparison(
    issue_id: str,
    publisher_ids: list[str],
    result: dict,
) -> Path:
    """
    선택 언론사 비교 결과를 캐시에 저장한다.
    """
    ensure_cache_directories()

    cache_key = make_comparison_cache_key(
        issue_id,
        publisher_ids,
    )

    cache_path = (
        COMPARISON_CACHE_DIR
        / f"{cache_key}.json"
    )

    cache_data = {
        "cache_type": "publisher_comparison",
        "cache_key": cache_key,
        "issue_id": issue_id,
        "publisher_ids": sorted(
            publisher_ids
        ),
        "created_at": datetime.now(
            timezone.utc
        ).isoformat(),
        "result": result,
    }

    _write_cache_file(
        cache_path,
        cache_data,
    )

    return cache_path

def make_keyword_extraction_cache_key(
    query: str,
    data_version: str,
) -> str:
    """
    키워드 추출 결과의 캐시 키를 만든다.

    data_version(records.json 수정 시각)이 바뀌면 새 뉴스가 들어왔다는
    뜻이므로 키가 달라져 예전 캐시를 자동으로 무효화한다.
    """
    return make_cache_key(
        "keyword-extraction",
        KEYWORD_EXTRACTION_PROMPT_VERSION,
        data_version,
        str(query or "").strip().lower(),
    )


def get_keyword_extraction(
    query: str,
    data_version: str,
) -> dict | None:
    """
    저장된 키워드 추출 결과를 조회한다.
    """
    ensure_cache_directories()

    cache_key = make_keyword_extraction_cache_key(
        query,
        data_version,
    )

    cache_path = (
        KEYWORD_EXTRACTION_CACHE_DIR
        / f"{cache_key}.json"
    )

    cached_data = _read_cache_file(
        cache_path
    )

    if not cached_data:
        return None

    result = cached_data.get("result")

    if not isinstance(result, dict):
        return None

    return result


def save_keyword_extraction(
    query: str,
    data_version: str,
    result: dict,
) -> Path:
    """
    키워드 추출 결과를 캐시에 저장한다.

    articles_by_id처럼 매번 새로 조회 가능한 무거운 데이터는 저장하지
    않고, Solar가 실제로 판단한 부분(keywords 목록)만 저장한다.
    """
    ensure_cache_directories()

    cache_key = make_keyword_extraction_cache_key(
        query,
        data_version,
    )

    cache_path = (
        KEYWORD_EXTRACTION_CACHE_DIR
        / f"{cache_key}.json"
    )

    cache_data = {
        "cache_type": "keyword_extraction",
        "cache_key": cache_key,
        "query": query,
        "data_version": data_version,
        "created_at": datetime.now(
            timezone.utc
        ).isoformat(),
        "result": result,
    }

    _write_cache_file(
        cache_path,
        cache_data,
    )

    return cache_path
