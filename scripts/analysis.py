import hashlib
import uuid
import requests
import argparse
import json
import os
import threading
import time

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI

from cache import (
    get_publisher_analysis,
    save_publisher_analysis,
)


MODEL_NAME = "solar-pro3"
REQUEST_TIMEOUT_SECONDS = 60
MAX_RETRIES = 3
RETRY_WAIT_SECONDS = 2

DEFAULT_INPUT_PATH = Path(
    "data/representative_articles.json"
)
DEFAULT_OUTPUT_PATH = Path(
    "data/publisher_analyses.json"
)
UPSTASH_REDIS_REST_URL = os.getenv(
    "UPSTASH_REDIS_REST_URL",
    "",
).rstrip("/")

UPSTASH_REDIS_REST_TOKEN = os.getenv(
    "UPSTASH_REDIS_REST_TOKEN",
    "",
)

DISTRIBUTED_LOCK_TTL_SECONDS = 300
DISTRIBUTED_RESULT_TTL_SECONDS = 21600
DISTRIBUTED_WAIT_TIMEOUT_SECONDS = 310
DISTRIBUTED_POLL_INTERVAL_SECONDS = 1
def is_distributed_single_flight_enabled() -> bool:
    """
    Upstash Redis 환경변수가 모두 설정되어 있는지 확인한다.
    """
    return bool(
        UPSTASH_REDIS_REST_URL
        and UPSTASH_REDIS_REST_TOKEN
    )


def execute_redis_command(
    *command_parts: Any,
) -> Any:
    """
    Upstash REST API를 통해 Redis 명령 하나를 실행한다.
    """
    if not is_distributed_single_flight_enabled():
        raise RuntimeError(
            "Upstash Redis 환경변수가 설정되지 않았습니다."
        )

    response = requests.post(
        UPSTASH_REDIS_REST_URL,
        headers={
            "Authorization": (
                f"Bearer {UPSTASH_REDIS_REST_TOKEN}"
            ),
            "Content-Type": "application/json",
        },
        json=list(command_parts),
        timeout=10,
    )

    response.raise_for_status()

    response_data = response.json()

    if not isinstance(response_data, dict):
        raise RuntimeError(
            "Upstash Redis 응답 형식이 올바르지 않습니다."
        )

    redis_error = response_data.get("error")

    if redis_error:
        raise RuntimeError(
            f"Upstash Redis 명령 실패: {redis_error}"
        )

    return response_data.get("result")

def build_distributed_single_flight_keys(
    single_flight_key: str,
) -> tuple[str, str]:
    """
    긴 요청 키를 SHA-256 해시로 변환해
    Redis lock 키와 결과 키를 만든다.
    """
    key_hash = hashlib.sha256(
        single_flight_key.encode("utf-8")
    ).hexdigest()

    lock_key = (
        f"prism:singleflight:lock:{key_hash}"
    )
    result_key = (
        f"prism:singleflight:result:{key_hash}"
    )

    return lock_key, result_key
def try_acquire_distributed_lock(
    lock_key: str,
    owner_token: str,
) -> bool:
    """
    Redis에 lock이 없을 때만 새 lock을 만든다.
    """
    result = execute_redis_command(
        "SET",
        lock_key,
        owner_token,
        "NX",
        "EX",
        DISTRIBUTED_LOCK_TTL_SECONDS,
    )

    return result == "OK"
_SINGLE_FLIGHT_LOCK = threading.Lock()
_SINGLE_FLIGHT_JOBS: dict[str, dict[str, Any]] = {}

def get_distributed_result(
    result_key: str,
) -> dict | None:
    """
    Redis에 저장된 완료 결과를 읽는다.
    결과가 없으면 None을 반환한다.
    """
    stored_result = execute_redis_command(
        "GET",
        result_key,
    )

    if stored_result is None:
        return None

    if not isinstance(stored_result, str):
        raise RuntimeError(
            "Redis에 저장된 분석 결과 형식이 올바르지 않습니다."
        )

    parsed_result = json.loads(
        stored_result
    )

    if not isinstance(parsed_result, dict):
        raise RuntimeError(
            "Redis 분석 결과가 객체 형식이 아닙니다."
        )

    return parsed_result
def save_distributed_result(
    result_key: str,
    result: dict,
) -> None:
    """
    완료된 분석 결과를 Redis에 TTL과 함께 저장한다.
    """
    serialized_result = json.dumps(
        result,
        ensure_ascii=False,
        separators=(",", ":"),
    )

    execute_redis_command(
        "SET",
        result_key,
        serialized_result,
        "EX",
        DISTRIBUTED_RESULT_TTL_SECONDS,
    )
def release_distributed_lock(
    lock_key: str,
    owner_token: str,
) -> None:
    """
    현재 요청이 소유한 lock일 때만 안전하게 삭제한다.
    """
    release_script = """
    if redis.call("GET", KEYS[1]) == ARGV[1] then
        return redis.call("DEL", KEYS[1])
    end
    return 0
    """

    execute_redis_command(
        "EVAL",
        release_script,
        1,
        lock_key,
        owner_token,
    )
def wait_for_distributed_result(
    lock_key: str,
    result_key: str,
) -> dict | None:
    """
    다른 인스턴스의 분석 완료 결과를 기다린다.

    결과가 저장되면 반환한다.
    lock이 사라졌는데 결과가 없으면 None을 반환해
    현재 요청이 다시 lock 획득을 시도하게 한다.
    """
    deadline = (
        time.monotonic()
        + DISTRIBUTED_WAIT_TIMEOUT_SECONDS
    )

    while time.monotonic() < deadline:
        shared_result = get_distributed_result(
            result_key
        )

        if shared_result is not None:
            return shared_result

        current_lock = execute_redis_command(
            "GET",
            lock_key,
        )

        if current_lock is None:
            return None

        time.sleep(
            DISTRIBUTED_POLL_INTERVAL_SECONDS
        )

    raise TimeoutError(
        "동일 분석의 선행 작업 완료를 "
        "기다리는 시간이 초과되었습니다."
    )

def build_issue_single_flight_key(
    input_data: dict,
) -> str:
    """
    같은 이슈·같은 언론사·같은 기사 구성인지 판단할 키를 만든다.
    """
    publishers = input_data.get(
        "publishers",
        [],
    )

    normalized_publishers = []

    if isinstance(publishers, list):
        for publisher_item in publishers:
            if not isinstance(
                publisher_item,
                dict,
            ):
                continue

            articles = publisher_item.get(
                "articles",
                [],
            )

            normalized_articles = []

            if isinstance(articles, list):
                for article in articles:
                    if not isinstance(
                        article,
                        dict,
                    ):
                        continue

                    normalized_articles.append(
                        {
                            "article_id": clean_string(
                                article.get(
                                    "article_id"
                                )
                            ),
                            "updated_at": clean_string(
                                article.get(
                                    "updated_at"
                                )
                            ),
                        }
                    )

            normalized_articles.sort(
                key=lambda article: (
                    article["article_id"],
                    article["updated_at"],
                )
            )

            normalized_publishers.append(
                {
                    "publisher_id": clean_string(
                        publisher_item.get(
                            "publisher_id"
                        )
                    ),
                    "articles": normalized_articles,
                }
            )

    normalized_publishers.sort(
        key=lambda publisher: (
            publisher["publisher_id"]
        )
    )

    return json.dumps(
        {
            "issue_id": clean_string(
                input_data.get(
                    "issue_id"
                )
            ),
            "publishers": normalized_publishers,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def load_json(path: Path) -> dict:
    """
    UTF-8 JSON 파일을 읽어 딕셔너리로 반환한다.
    """
    if not path.exists():
        raise FileNotFoundError(
            f"입력 파일을 찾을 수 없습니다: {path}"
        )

    with path.open(
        "r",
        encoding="utf-8",
    ) as file:
        data = json.load(file)

    if not isinstance(data, dict):
        raise ValueError(
            f"JSON 최상위 값은 객체여야 합니다: {path}"
        )

    return data


def save_json(
    path: Path,
    data: dict,
) -> None:
    """
    결과를 UTF-8 JSON 파일로 저장한다.
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


def create_client() -> OpenAI:
    """
    환경변수의 Upstage API 키로 클라이언트를 생성한다.
    """
    load_dotenv()

    api_key = os.getenv(
        "UPSTAGE_API_KEY"
    )

    if not api_key:
        raise ValueError(
            "UPSTAGE_API_KEY가 설정되지 않았습니다. "
            ".env 파일을 확인하세요."
        )

    return OpenAI(
        api_key=api_key,
        base_url="https://api.upstage.ai/v1",
    )


def clean_string(value: Any) -> str:
    """
    문자열이 아닌 값은 빈 문자열로 바꾸고
    문자열의 앞뒤 공백을 제거한다.
    """
    if not isinstance(value, str):
        return ""

    return value.strip()


def clean_string_list(
    values: Any,
    max_items: int = 8,
) -> list[str]:
    """
    문자열 배열을 정리한다.

    - 빈 값 제거
    - 중복 제거
    - 최대 개수 제한
    """
    if not isinstance(values, list):
        return []

    cleaned_values = []
    seen = set()

    for value in values:
        if not isinstance(value, str):
            continue

        value = value.strip()

        if not value:
            continue

        normalized = value.replace(
            " ",
            "",
        )

        if normalized in seen:
            continue

        seen.add(normalized)
        cleaned_values.append(value)

        if len(cleaned_values) >= max_items:
            break

    return cleaned_values


def normalize_articles(
    articles: Any,
) -> list[dict]:
    """
    대표 기사 입력값을 분석에 필요한 공통 구조로 정리한다.
    """
    if not isinstance(articles, list):
        raise ValueError(
            "articles는 배열이어야 합니다."
        )

    if not articles:
        raise ValueError(
            "분석할 대표 기사가 없습니다."
        )

    if len(articles) > 2:
        raise ValueError(
            "언론사별 대표 기사는 최대 2개만 허용됩니다."
        )

    normalized_articles = []

    for index, article in enumerate(
        articles,
        start=1,
    ):
        if not isinstance(article, dict):
            raise ValueError(
                f"articles[{index - 1}]은 객체여야 합니다."
            )

        article_id = clean_string(
            article.get("article_id")
        )

        title = clean_string(
            article.get("title")
        )

        if not article_id:
            raise ValueError(
                f"{index}번째 기사에 article_id가 없습니다."
            )

        if not title:
            raise ValueError(
                f"{index}번째 기사에 title이 없습니다."
            )

        normalized_articles.append(
            {
                "article_id": article_id,
                "title": title,
                "description": clean_string(
                    article.get("description")
                ),
                "published_at": clean_string(
                    article.get("published_at")
                    or article.get("published")
                ) or "발행 시간 정보 없음",
                "link": clean_string(
                    article.get("link")
                ),
                "category": clean_string(
                    article.get("category")
                ),
            }
        )

    return normalized_articles


def build_article_text(
    articles: list[dict],
) -> str:
    """
    대표 기사 목록을 Solar 프롬프트에 넣을 텍스트로 변환한다.
    """
    sections = []

    for index, article in enumerate(
        articles,
        start=1,
    ):
        sections.append(
            f"""
기사 {index}
기사 ID: {article["article_id"]}
제목: {article["title"]}
RSS 설명: {article["description"]}
발행 시각: {article["published_at"]}
카테고리: {article["category"]}
원문 링크: {article["link"]}
""".strip()
        )

    return "\n\n--------------------\n\n".join(
        sections
    )


def build_publisher_prompt(
    issue_id: str,
    issue_title: str,
    publisher_id: str,
    publisher: str,
    articles: list[dict],
) -> str:
    """
    언론사 한 곳의 대표 기사 1~2개를 분석하기 위한
    Solar 프롬프트를 생성한다.
    """
    article_text = build_article_text(
        articles
    )

    return f"""
당신은 뉴스 기사 비교 서비스 Prism의 언론사별 기사 분석기입니다.

이번 요청에서는 여러 언론사를 서로 비교하지 않습니다.
하나의 언론사가 동일 이슈를 다룬 대표 기사 1~2개만 분석합니다.

분석 대상 이슈:
- 이슈 ID: {issue_id}
- 이슈명: {issue_title}
- 언론사 ID: {publisher_id}
- 언론사명: {publisher}

분석 자료의 범위:
- 기사 제목
- RSS 설명
- 발행 시각
- 원문 링크

중요 원칙:
- 제공된 제목과 RSS 설명에서 확인되는 내용만 사용하세요.
- 기사 원문 전체를 읽은 것처럼 작성하지 마세요.
- 언론사의 정치 성향이나 고정된 성격을 판단하지 마세요.
- 기자 또는 언론사의 의도를 추측하지 마세요.
- 해당 기사 세트에서 실제로 강조된 내용만 분석하세요.
- 근거가 부족하면 억지로 차이나 프레임을 만들지 마세요.
- 분석 근거에는 제목 또는 RSS 설명에서 실제로 확인되는 표현을 적으세요.
- 동일한 내용을 반복하지 마세요.
- 모든 배열은 확인 가능한 항목만 포함하세요.
- 정보가 없으면 빈 문자열 또는 빈 배열을 사용하세요.
- JSON 이외의 설명은 출력하지 마세요.

분석 항목:

1. article_summary
대표 기사에 공통으로 나타나는 내용을 1~2문장으로 요약합니다.

2. headline_frame
제목이 사건의 어떤 요소를 중심에 놓는지 설명합니다.

3. main_focus
해당 언론사가 기사에서 가장 중요하게 다루는 핵심 관점을 설명합니다.

4. primary_frame
기사에서 가장 중심적으로 나타나는 프레임을 다음 구조로 정리합니다.

- category:
  기사가 사건을 바라보는 중심 문제 유형을 짧은 자유형 문자열로 작성합니다.

- stance:
  프레임의 대상이나 상황에 대해 기사에서 나타나는 평가 또는 입장 방향을
  짧은 자유형 문자열로 작성합니다.

- target:
  해당 프레임이 주로 향하는 인물·집단·기관·정책·제도·현상 등을
  짧은 자유형 문자열로 작성합니다.

- summary:
  category, stance, target이 기사에서 어떻게 나타나는지 1~2문장으로
  구체적으로 설명합니다.

- evidence:
  해당 프레임을 판단한 근거가 되는 제목 또는 RSS 설명의 실제 표현을
  배열로 제시합니다.

category, stance, target에는 미리 정해진 선택지가 없습니다.
다른 기사 및 언론사와 비교할 수 있도록 지나치게 길거나 추상적인 표현은 피하고,
핵심 의미가 드러나는 간결한 표현을 사용하세요.

summary는 headline_frame이나 main_focus를 그대로 반복하지 말고,
어떤 대상을 어떤 문제 유형과 입장으로 다루는지가 드러나도록 작성하세요.

primary_frame은 기사에서 확인되는 가장 중심적인 보도 구성을 반드시 정리하세요.
기사 제목이나 RSS 설명에서 중심 대상, 문제 유형, 강조 방향 중 하나라도
확인할 수 있다면 category, stance, target, summary를 작성해야 합니다.

stance는 반드시 긍정·부정과 같은 평가만 의미하지 않습니다.
평가가 뚜렷하지 않은 설명 기사에서는
"사실 전달", "상황 강조", "피해 조명", "전망 제시"처럼
기사의 서술 방향을 자유형 문자열로 작성할 수 있습니다.

evidence에는 primary_frame을 판단하는 데 사용한 제목 또는 RSS 설명의
실제 표현을 최소 1개 이상 제시하세요.

기사 제목과 RSS 설명이 모두 비어 있거나,
프레임을 판단할 실제 표현이 전혀 없는 경우에만
category, stance, target, summary를 빈 문자열로 작성하고
evidence를 빈 배열로 작성하세요.

5. keywords
기사의 핵심 개념을 3~6개 제시합니다.
인물명과 기관명은 제외합니다.

6. main_actors
기사에서 주요 행동 주체로 다뤄지는 인물·집단·기관을 제시합니다.

7. quoted_sources
기사 설명에서 직접 인용하거나 입장을 전달한 대상이 확인되면 제시합니다.

8. causes
기사에서 사건의 직접적인 원인으로 강조한 내용을 제시합니다.

9. background
사건을 이해하기 위한 제도적·사회적·경제적 배경으로 다룬 내용을 제시합니다.

10. emphasized_effects
기사에서 중요하게 다룬 결과·영향·위험·변화를 제시합니다.

11. affected_groups
기사에서 영향을 받는 대상으로 강조한 사람·집단·기관을 제시합니다.

12. tone
보도 태도를 category와 evidence로 구분합니다.

category는 다음 중 하나만 사용하세요.
- 중립 설명
- 분석·전망
- 우려·경계
- 비판
- 기대
- 갈등 강조
- 판단 어려움

evidence에는 해당 태도를 판단한 실제 제목 또는 RSS 설명 표현을 최소 1개
이상 반드시 제시하세요. category만 쓰고 evidence를 비워두지 마세요.
판단할 근거를 정말 찾을 수 없는 경우에만 category를 "판단 어려움"으로
쓰고 evidence를 비워두세요.

13. outlook
기사에서 향후 전망이 확인되면 direction과 summary로 정리합니다.

direction은 다음 중 하나만 사용하세요.
- 긍정
- 부정
- 혼합
- 중립
- 전망 없음

14. less_covered_context
현재 제공된 기사에서 상대적으로 확인하기 어려운 관련 맥락을 제시합니다.
기사에 없는 사실을 새로 만들어서는 안 됩니다.
예: "정책 시행 이후의 구체적 효과는 확인하기 어렵다."

반드시 아래 JSON 구조로만 응답하세요.

{{
  "issue_id": "{issue_id}",
  "publisher_id": "{publisher_id}",
  "publisher": "{publisher}",
  "articles": [
    {{
      "article_id": "입력된 기사 ID",
      "title": "입력된 기사 제목",
      "published_at": "입력된 발행 시각",
      "link": "입력된 원문 링크"
    }}
  ],
  "analysis": {{
    "article_summary": "",
    "headline_frame": "",
    "main_focus": "",
    "primary_frame": {{
      "category": "",
      "stance": "",
      "target": "",
      "summary": "",
      "evidence": []
    }},
    "keywords": [],
    "main_actors": [],
    "quoted_sources": [],
    "causes": [],
    "background": [],
    "emphasized_effects": [],
    "affected_groups": [],
    "tone": {{
      "category": "",
      "evidence": []
    }},
    "outlook": {{
      "direction": "",
      "summary": ""
    }},
    "less_covered_context": [],
    "evidence_limit": "기사 제목과 RSS 설명 기준"
  }}
}}

분석할 대표 기사:

{article_text}
""".strip()


def validate_analysis_result(
    result: Any,
    issue_id: str,
    publisher_id: str,
    publisher: str,
    source_articles: list[dict],
) -> dict:
    """
    Solar 결과가 고정된 Structured Output을 따르는지 검사하고,
    누락되거나 불안정한 값을 정리한다.
    """
    if not isinstance(result, dict):
        raise ValueError(
            "Solar 응답의 최상위 값이 객체가 아닙니다."
        )

    analysis = result.get("analysis")

    if not isinstance(analysis, dict):
        raise ValueError(
            "Solar 응답에 analysis 객체가 없습니다."
        )

    primary_frame = analysis.get(
        "primary_frame"
    )

    if not isinstance(primary_frame, dict):
        primary_frame = {}

    tone = analysis.get("tone")

    if not isinstance(tone, dict):
        tone = {}

    outlook = analysis.get("outlook")

    if not isinstance(outlook, dict):
        outlook = {}

    allowed_tones = {
        "중립 설명",
        "분석·전망",
        "우려·경계",
        "비판",
        "기대",
        "갈등 강조",
        "판단 어려움",
    }

    tone_category = clean_string(
        tone.get("category")
    )

    if tone_category not in allowed_tones:
        tone_category = "판단 어려움"

    tone_evidence = clean_string_list(
        tone.get("evidence"),
        max_items=5,
    )

    # "판단 어려움"이 아닌 태도를 붙였다면 근거 없이 통과시키지 않는다 —
    # 근거를 못 찾으면 category 자체를 "판단 어려움"으로 썼어야 한다.
    if (
        tone_category != "판단 어려움"
        and not tone_evidence
    ):
        raise ValueError(
            f"tone.category가 '{tone_category}'인데 "
            "tone.evidence가 비어 있습니다."
        )

    allowed_outlook_directions = {
        "긍정",
        "부정",
        "혼합",
        "중립",
        "전망 없음",
    }

    outlook_direction = clean_string(
        outlook.get("direction")
    )

    if (
        outlook_direction
        not in allowed_outlook_directions
    ):
        outlook_direction = "전망 없음"

    normalized_result = {
        "issue_id": issue_id,
        "publisher_id": publisher_id,
        "publisher": publisher,
        "articles": [
            {
                "article_id": article[
                    "article_id"
                ],
                "title": article["title"],
                "published_at": article[
                    "published_at"
                ],
                "link": article["link"],
            }
            for article in source_articles
        ],
        "analysis": {
            "article_summary": clean_string(
                analysis.get(
                    "article_summary"
                )
            ),
            "headline_frame": clean_string(
                analysis.get(
                    "headline_frame"
                )
            ),
            "main_focus": clean_string(
                analysis.get(
                    "main_focus"
                )
            ),
            "primary_frame": {
                "category": clean_string(
                    primary_frame.get(
                        "category"
                    )
                ),
                "stance": clean_string(
                    primary_frame.get(
                        "stance"
                    )
                ),
                "target": clean_string(
                    primary_frame.get(
                        "target"
                    )
                ),
                "summary": clean_string(
                    primary_frame.get(
                        "summary"
                    )
                ),
                "evidence": clean_string_list(
                    primary_frame.get(
                        "evidence"
                    ),
                    max_items=5,
                ),
            },
            "keywords": clean_string_list(
                analysis.get("keywords"),
                max_items=6,
            ),
            "main_actors": clean_string_list(
                analysis.get(
                    "main_actors"
                ),
                max_items=8,
            ),
            "quoted_sources": clean_string_list(
                analysis.get(
                    "quoted_sources"
                ),
                max_items=8,
            ),
            "causes": clean_string_list(
                analysis.get("causes"),
                max_items=6,
            ),
            "background": clean_string_list(
                analysis.get(
                    "background"
                ),
                max_items=6,
            ),
            "emphasized_effects": (
                clean_string_list(
                    analysis.get(
                        "emphasized_effects"
                    ),
                    max_items=6,
                )
            ),
            "affected_groups": (
                clean_string_list(
                    analysis.get(
                        "affected_groups"
                    ),
                    max_items=6,
                )
            ),
            "tone": {
                "category": tone_category,
                "evidence": tone_evidence,
            },
            "outlook": {
                "direction": (
                    outlook_direction
                ),
                "summary": clean_string(
                    outlook.get("summary")
                ),
            },
            "less_covered_context": (
                clean_string_list(
                    analysis.get(
                        "less_covered_context"
                    ),
                    max_items=5,
                )
            ),
            "evidence_limit": (
                "기사 제목과 RSS 설명 기준"
            ),
        },
        "analysis_status": "success",
        "analyzed_at": datetime.now(
            timezone.utc
        ).isoformat(),
        "model": MODEL_NAME,
    }

    if not normalized_result[
        "analysis"
    ]["article_summary"]:
        raise ValueError(
            "article_summary가 비어 있습니다."
        )

    if not normalized_result[
        "analysis"
    ]["main_focus"]:
        raise ValueError(
            "main_focus가 비어 있습니다."
        )

    return normalized_result


def request_solar_analysis(
    client: OpenAI,
    prompt: str,
) -> dict:
    """
    Solar API를 호출하고 JSON 응답을 파싱한다.
    """
    response = client.chat.completions.create(
        model=MODEL_NAME,
        messages=[
            {
                "role": "user",
                "content": prompt,
            }
        ],
        response_format={
            "type": "json_object",
        },
        temperature=0,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )

    content = (
        response
        .choices[0]
        .message
        .content
    )

    if not content:
        raise ValueError(
            "Solar 응답 내용이 비어 있습니다."
        )

    try:
        result = json.loads(content)

    except json.JSONDecodeError as error:
        raise ValueError(
            "Solar 응답을 JSON으로 해석할 수 없습니다."
        ) from error

    if not isinstance(result, dict):
        raise ValueError(
            "Solar 응답이 JSON 객체가 아닙니다."
        )

    return result


def analyze_publisher(
    client: OpenAI,
    issue_id: str,
    issue_title: str,
    publisher_id: str,
    publisher: str,
    articles: list[dict],
    use_cache: bool = True,
) -> dict:
    """
    언론사 한 곳의 대표 기사 1~2개를 분석한다.

    처리 순서:
    1. 입력 기사 정리
    2. 캐시 조회
    3. Solar 분석
    4. Structured Output 검증
    5. 캐시 저장
    """
    normalized_articles = normalize_articles(
        articles
    )

    article_ids = [
        article["article_id"]
        for article in normalized_articles
    ]

    if use_cache:
        cached_result = (
            get_publisher_analysis(
                issue_id=issue_id,
                publisher_id=publisher_id,
                article_ids=article_ids,
            )
        )

        if cached_result:
            print(
                f"[캐시 사용] "
                f"{publisher} 분석 결과"
            )

            return cached_result

    prompt = build_publisher_prompt(
        issue_id=issue_id,
        issue_title=issue_title,
        publisher_id=publisher_id,
        publisher=publisher,
        articles=normalized_articles,
    )

    last_error = None

    for attempt in range(
        1,
        MAX_RETRIES + 1,
    ):
        try:
            print(
                f"[Solar 분석] {publisher} "
                f"{attempt}/{MAX_RETRIES}"
            )

            raw_result = request_solar_analysis(
                client=client,
                prompt=prompt,
            )

            validated_result = (
                validate_analysis_result(
                    result=raw_result,
                    issue_id=issue_id,
                    publisher_id=publisher_id,
                    publisher=publisher,
                    source_articles=(
                        normalized_articles
                    ),
                )
            )

            save_publisher_analysis(
                issue_id=issue_id,
                publisher_id=publisher_id,
                article_ids=article_ids,
                result=validated_result,
            )

            print(
                f"[분석 완료] {publisher}"
            )

            return validated_result

        except Exception as error:
            last_error = error

            print(
                f"[분석 실패] {publisher} "
                f"{attempt}/{MAX_RETRIES}: "
                f"{error}"
            )

            if attempt < MAX_RETRIES:
                time.sleep(
                    RETRY_WAIT_SECONDS
                )

    raise RuntimeError(
        f"{publisher} 분석이 "
        f"{MAX_RETRIES}회 모두 실패했습니다: "
        f"{last_error}"
    )


def analyze_input_data(
    input_data: dict,
    use_cache: bool = True,
) -> dict:
    """
    JSON 입력 파일에서 언론사 한 곳의 정보를 읽고 분석한다.
    """
    issue_id = clean_string(
        input_data.get("issue_id")
    )

    issue_title = clean_string(
        input_data.get("issue_title")
    )

    publisher_id = clean_string(
        input_data.get("publisher_id")
    )

    publisher = clean_string(
        input_data.get("publisher")
    )

    articles = input_data.get(
        "articles",
        [],
    )

    if not issue_id:
        raise ValueError(
            "issue_id가 없습니다."
        )

    if not issue_title:
        raise ValueError(
            "issue_title이 없습니다."
        )

    if not publisher_id:
        raise ValueError(
            "publisher_id가 없습니다."
        )

    if not publisher:
        raise ValueError(
            "publisher가 없습니다."
        )

    client = create_client()

    return analyze_publisher(
        client=client,
        issue_id=issue_id,
        issue_title=issue_title,
        publisher_id=publisher_id,
        publisher=publisher,
        articles=articles,
        use_cache=use_cache,
    )
def normalize_grouping_analyses(
    publisher_analyses: Any,
) -> list[dict]:
    """
    Publisher Grouping에 사용할 언론사별 분석 결과를 검증한다.
    """
    if not isinstance(publisher_analyses, list):
        raise ValueError(
            "publisher_analyses는 배열이어야 합니다."
        )

    if len(publisher_analyses) < 2:
        raise ValueError(
            "경향 그룹을 만들려면 최소 2개 언론사가 필요합니다."
        )

    normalized = []
    seen_publishers = set()
    issue_ids = set()

    for index, item in enumerate(
        publisher_analyses
    ):
        if not isinstance(item, dict):
            raise ValueError(
                f"publisher_analyses[{index}]는 객체여야 합니다."
            )

        issue_id = clean_string(
            item.get("issue_id")
        )

        publisher_id = clean_string(
            item.get("publisher_id")
        )

        publisher = clean_string(
            item.get("publisher")
        )

        analysis = item.get("analysis")

        if not issue_id:
            raise ValueError(
                f"{index + 1}번째 분석 결과에 issue_id가 없습니다."
            )

        if not publisher_id:
            raise ValueError(
                f"{index + 1}번째 분석 결과에 publisher_id가 없습니다."
            )

        if not publisher:
            raise ValueError(
                f"{index + 1}번째 분석 결과에 publisher가 없습니다."
            )

        if not isinstance(analysis, dict):
            raise ValueError(
                f"{publisher}의 analysis가 객체가 아닙니다."
            )

        if publisher_id in seen_publishers:
            raise ValueError(
                f"중복된 언론사입니다: {publisher_id}"
            )

        seen_publishers.add(
            publisher_id
        )

        issue_ids.add(issue_id)

        normalized.append(
            {
                "issue_id": issue_id,
                "publisher_id": publisher_id,
                "publisher": publisher,
                "analysis": analysis,
            }
        )

    if len(issue_ids) != 1:
        raise ValueError(
            "서로 다른 이슈의 언론사 분석 결과는 "
            "하나의 경향 그룹으로 묶을 수 없습니다."
        )

    return normalized


def build_grouping_text(
    publisher_analyses: list[dict],
) -> str:
    """
    언론사별 Structured Output을 그룹화용 텍스트로 변환한다.
    """
    sections = []

    for item in publisher_analyses:
        analysis = item["analysis"]

        sections.append(
            f"""
언론사 ID: {item["publisher_id"]}
언론사명: {item["publisher"]}

제목 프레임:
{analysis.get("headline_frame", "")}

핵심 관점:
{analysis.get("main_focus", "")}

핵심 키워드:
{json.dumps(
    analysis.get("keywords", []),
    ensure_ascii=False,
)}

강조된 원인:
{json.dumps(
    analysis.get("causes", []),
    ensure_ascii=False,
)}

강조된 배경:
{json.dumps(
    analysis.get("background", []),
    ensure_ascii=False,
)}

강조된 영향:
{json.dumps(
    analysis.get("emphasized_effects", []),
    ensure_ascii=False,
)}

영향 대상:
{json.dumps(
    analysis.get("affected_groups", []),
    ensure_ascii=False,
)}

보도 태도:
{json.dumps(
    analysis.get("tone", {}),
    ensure_ascii=False,
)}

향후 전망:
{json.dumps(
    analysis.get("outlook", {}),
    ensure_ascii=False,
)}
""".strip()
        )

    return "\n\n====================\n\n".join(
        sections
    )


def build_grouping_prompt(
    issue_id: str,
    publisher_analyses: list[dict],
) -> str:
    """
    언론사별 분석 결과를 핵심 관점과 보도 경향에 따라
    그룹으로 묶기 위한 Solar 프롬프트를 생성한다.
    """
    grouping_text = build_grouping_text(
        publisher_analyses
    )

    publisher_count = len(
        publisher_analyses
    )

    maximum_group_count = min(
        5,
        publisher_count,
    )

    return f"""
당신은 뉴스 기사 비교 서비스 Prism의
보도 경향 그룹 분석기입니다.

입력 데이터는 동일한 이슈를 다룬 언론사별 기사 분석 결과입니다.
각 언론사가 사건에서 무엇을 핵심 쟁점으로 다루고,
그 사건을 어떤 방향으로 해석하고 평가하는지를 중심으로 그룹화하세요.

이슈 ID:
{issue_id}

언론사 수:
{publisher_count}

가장 중요한 분류 기준:
- 핵심 관점(main_focus)을 최우선 기준으로 사용하세요.
- 핵심 관점은 단순한 주제나 공통 키워드가 아니라,
  기사가 사건에서 가장 중요하다고 보는 쟁점과 해석 방향을 의미합니다.
- 핵심 관점의 문장 표현이나 세부 정보가 조금 다르다는 이유만으로
  서로 다른 그룹으로 분리하지 마세요.
- 중심 쟁점과 해석 방향이 대체로 같고 서로 충돌하지 않으면
  같은 그룹으로 묶을 수 있습니다.
- 반대로 사건에 부여한 핵심 의미나 평가 방향이 서로 대립하거나
  양립하기 어려운 경우에는 다른 그룹으로 구분하세요.

판단 순서:
1. 핵심 관점(main_focus)
   - 기사가 중심적으로 다루는 쟁점이 같은가?
   - 사건에 부여한 의미와 해석 방향이 대체로 같은가?
   - 두 핵심 관점이 서로 보완 가능한가,
     아니면 서로 대립하거나 양립하기 어려운가?
   - 정책의 내용·효과를 설명하는 관점인가,
     정책 실패·피해·책임을 비판하는 관점인가?

2. 강조된 원인·배경
   - 지목하는 원인, 책임 주체 또는 배경이 같은 방향인가?
   - 세부 원인이 다르더라도 전체 해석을 바꾸는 차이인지 판단하세요.

3. 강조한 영향·대상
   - 강조하는 영향과 그 영향이 향하는 대상이 같은가?
   - 세부 대상이나 사례만 다른지,
     핵심적인 영향 해석 자체가 다른지 구분하세요.

4. 보도 태도(tone)
   - 긍정, 부정, 중립, 혼합 중 같은 방향인가?
   - 단순한 문체가 아니라 설명, 전망, 우려, 비판,
     책임 추궁 등의 태도가 같은지 확인하세요.

분류 결정 규칙:
- 핵심 관점의 중심 쟁점과 해석 방향이 대체로 같고
  서로 충돌하지 않으면 같은 그룹으로 묶으세요.
- 핵심 관점이 같은 경우에는 원인·배경, 영향·대상,
  보도 태도를 종합하여 최종적으로 판단하세요.
- 핵심 관점의 표현, 세부 대상, 사례, 근거 또는 강조 강도만 다르다면
  별도 그룹으로 나누지 마세요.
- 원인·배경이나 영향·대상이 일부 다르더라도,
  그 차이가 핵심 해석을 바꾸지 않으면 같은 그룹으로 묶을 수 있습니다.
- 사건에 부여한 핵심 의미나 평가 방향이 서로 대립하거나
  양립하기 어려운 경우에는 다른 그룹으로 구분하세요.
- 정책 효과·필요성을 설명하는 관점과
  정책 실패·피해·부작용을 비판하는 관점은
  핵심 해석이 다르므로 별도 그룹으로 구분하세요.
- 동일한 정책명, 기관명, 인물명 또는 사건명이 등장한다는 이유만으로
  같은 그룹으로 묶지 마세요.

반드시 분리해야 하는 예시:
- A 언론사:
  정부 규제 조치의 내용과 시장 안정 효과를 중립적으로 설명
- B 언론사:
  같은 규제로 인한 국민 피해와 정부 경제정책 실패를 비판

위 두 언론사는 동일한 정책을 다루지만,
사건에 부여한 핵심 의미와 평가 방향이 서로 다르므로
서로 다른 그룹으로 분류하세요.

같은 그룹으로 묶을 수 있는 예시:
- A 언론사:
  정부 규제 조치가 시장 과열을 줄일 수 있다고 설명
- B 언론사:
  규제 시행 과정과 시장 안정 가능성을 중심으로 설명

위 두 언론사는 표현과 세부 정보는 다르지만,
규제의 내용과 시장 안정 효과를 중심으로 본다는 점에서
핵심 해석이 충돌하지 않으므로 같은 그룹으로 묶을 수 있습니다.

추가 분리 예시:
- 제도의 필요성과 기대 효과 설명
  vs 제도의 위험성과 부작용 비판
- 사건 경과 전달
  vs 특정 주체의 책임 추궁

분리하지 않아야 하는 경우:
- 중심 쟁점과 해석 방향은 같고 세부 사례, 피해 대상의 표현,
  근거 수치 또는 강조 강도만 다른 경우

그룹화 원칙:
- 현재 제공된 기사 분석 결과만 사용하세요.
- 앞서 제시한 핵심 관점 기준을 우선 적용하고,
  세부 표현 차이만으로 그룹을 과도하게 나누지 마세요.
- 그룹 수를 줄이기 위해 명확히 다른 핵심 관점을 합치지 마세요.
- 1개 언론사만 다른 핵심 관점을 보이는 경우에도,
  다른 그룹과 핵심 해석이 명확히 구분될 때만 독립 그룹을 허용하세요.
- 차이가 명확하지 않으면 같은 그룹으로 묶을 수 있습니다.
- 모든 언론사는 정확히 한 개 그룹에만 포함해야 합니다.
- 어떤 언론사도 누락하거나 중복하지 마세요.
- 그룹명은 해당 기사들의 공통된 핵심 관점을 나타내는
  짧은 명사구로 작성하세요.
- 그룹명 예시는
  "규제 효과와 시장 안정 전망",
  "국민 피해와 정책 실패 비판",
  "정책 추진 과정 설명",
  "투자 위험과 부작용 경고"
  같은 형식입니다.
- 언론사 수보다 많은 그룹을 만들지 마세요.
- 전체 언론사의 핵심 관점이 실질적으로 유사하면
  그룹 수를 줄일 수 있습니다.
- 그룹 수는 1개 이상 {maximum_group_count}개 이하로 작성하세요.
- JSON 이외의 문장은 출력하지 마세요.

그룹 근거 작성 규칙:
- group_evidence에는 단순 키워드가 아니라
  해당 그룹의 공통된 핵심 관점을 판단한 근거를 작성하세요.
- 각 근거에는 중심 쟁점, 해석 또는 평가 방향이 드러나야 합니다.
- 같은 그룹으로 묶은 경우에는
  표현 차이에도 불구하고 어떤 핵심 해석이 공통적인지 설명하세요.
- 별도 그룹으로 나눈 경우에는
  어떤 핵심 의미나 평가 방향이 충돌하는지 설명하세요.
- group_contrasts에는 그룹 간 핵심 관점 차이를 직접 대조하세요.

반드시 아래 JSON 구조로만 응답하세요.

{{
  "issue_id": "{issue_id}",
  "groups": [
    {{
      "group_id": "영문 소문자와 하이픈으로 작성한 그룹 ID",
      "label": "현재 기사에서 나타난 핵심 관점 중심의 그룹명",
      "summary": "이 그룹에 포함된 언론사들이 공통으로 강조한 핵심 관점 설명",
      "keywords": [
        "대표 키워드"
      ],
      "publisher_ids": [
        "언론사 ID"
      ],
      "group_evidence": [
        "중심 쟁점, 해석 또는 평가 방향을 포함한 그룹 구성 근거"
      ]
    }}
  ],
  "group_contrasts": [
    {{
      "group_ids": [
        "비교할 그룹 ID"
      ],
      "contrast_statement": "두 그룹의 핵심 관점과 평가 방향 차이를 직접 대조한 문장"
    }}
  ],
  "grouping_summary": "전체 핵심 관점과 보도 경향 분포를 종합한 설명",
  "evidence_limit": "기사 제목과 RSS 설명을 기반으로 생성된 언론사별 분석 결과 기준"
}}

언론사별 Structured Output:

{grouping_text}
""".strip()


def validate_grouping_result(
    result: Any,
    issue_id: str,
    publisher_analyses: list[dict],
) -> dict:
    """
    Solar의 Publisher Grouping 결과를 검증하고
    고정 JSON 구조로 정리한다.
    """
    if not isinstance(result, dict):
        raise ValueError(
            "그룹화 결과의 최상위 값이 객체가 아닙니다."
        )

    groups = result.get("groups")

    if not isinstance(groups, list):
        raise ValueError(
            "groups는 배열이어야 합니다."
        )

    if not groups:
        raise ValueError(
            "생성된 보도 경향 그룹이 없습니다."
        )

    expected_publishers = {
        item["publisher_id"]: item["publisher"]
        for item in publisher_analyses
    }

    maximum_group_count = min(
        5,
        len(expected_publishers),
    )

    if len(groups) > maximum_group_count:
        raise ValueError(
            f"그룹 수가 허용 범위를 초과했습니다: "
            f"{len(groups)}개"
        )

    normalized_groups = []
    assigned_publishers = set()
    seen_group_ids = set()

    for index, group in enumerate(
        groups,
        start=1,
    ):
        if not isinstance(group, dict):
            raise ValueError(
                f"groups[{index - 1}]은 객체여야 합니다."
            )

        group_id = clean_string(
            group.get("group_id")
        )

        if not group_id:
            group_id = f"group-{index}"

        if group_id in seen_group_ids:
            group_id = f"{group_id}-{index}"

        seen_group_ids.add(group_id)

        publisher_ids = group.get(
            "publisher_ids",
            [],
        )

        if not isinstance(publisher_ids, list):
            publisher_ids = []

        valid_publisher_ids = []

        for publisher_id in publisher_ids:
            publisher_id = clean_string(
                publisher_id
            )

            if (
                publisher_id
                not in expected_publishers
            ):
                continue

            if publisher_id in assigned_publishers:
                raise ValueError(
                    f"언론사가 여러 그룹에 중복되었습니다: "
                    f"{publisher_id}"
                )

            assigned_publishers.add(
                publisher_id
            )

            valid_publisher_ids.append(
                publisher_id
            )

        if not valid_publisher_ids:
            continue

        normalized_groups.append(
            {
                "group_id": group_id,
                "label": clean_string(
                    group.get("label")
                ) or f"보도 경향 그룹 {index}",
                "summary": clean_string(
                    group.get("summary")
                ),
                "keywords": clean_string_list(
                    group.get("keywords"),
                    max_items=6,
                ),
                "publisher_ids": (
                    valid_publisher_ids
                ),
                "publishers": [
                    {
                        "publisher_id": publisher_id,
                        "publisher": expected_publishers[
                            publisher_id
                        ],
                    }
                    for publisher_id
                    in valid_publisher_ids
                ],
                "publisher_count": len(
                    valid_publisher_ids
                ),
                "group_evidence": (
                    clean_string_list(
                        group.get(
                            "group_evidence"
                        ),
                        max_items=6,
                    )
                ),
            }
        )

    missing_publishers = (
        set(expected_publishers)
        - assigned_publishers
    )

    # Solar가 드물게 언론사 하나를 그룹 목록에서 누락시키는 경우
    # (temperature=0에서도 완전히 없어지지 않는 잔여 변동성) 전체 분석을
    # 실패시키는 대신, 누락된 언론사만 개별 그룹으로 만들어 복구한다.
    for publisher_id in sorted(missing_publishers):
        normalized_groups.append(
            {
                "group_id": f"group-ungrouped-{publisher_id}",
                "label": "개별 분류 (그룹화 보류)",
                "summary": (
                    f"{expected_publishers[publisher_id]}는 "
                    "다른 언론사와 뚜렷이 묶이지 않아 "
                    "그룹화 단계에서 개별로 분류되었습니다."
                ),
                "keywords": [],
                "publisher_ids": [publisher_id],
                "publishers": [
                    {
                        "publisher_id": publisher_id,
                        "publisher": expected_publishers[
                            publisher_id
                        ],
                    }
                ],
                "publisher_count": 1,
                "group_evidence": [],
            }
        )

    if not normalized_groups:
        raise ValueError(
            "유효한 보도 경향 그룹이 없습니다."
        )

    group_ids = {
        group["group_id"]
        for group in normalized_groups
    }

    raw_contrasts = result.get(
        "group_contrasts",
        [],
    )

    normalized_contrasts = []

    if isinstance(raw_contrasts, list):
        for contrast in raw_contrasts:
            if not isinstance(
                contrast,
                dict,
            ):
                continue

            contrast_group_ids = (
                contrast.get(
                    "group_ids",
                    [],
                )
            )

            if not isinstance(
                contrast_group_ids,
                list,
            ):
                continue

            valid_group_ids = [
                clean_string(group_id)
                for group_id
                in contrast_group_ids
                if clean_string(group_id)
                in group_ids
            ]

            if len(valid_group_ids) < 2:
                continue

            statement = clean_string(
                contrast.get(
                    "contrast_statement"
                )
            )

            if not statement:
                continue

            normalized_contrasts.append(
                {
                    "group_ids": (
                        valid_group_ids[:2]
                    ),
                    "contrast_statement": (
                        statement
                    ),
                }
            )

    return {
        "issue_id": issue_id,
        "groups": normalized_groups,
        "group_count": len(
            normalized_groups
        ),
        "group_contrasts": (
            normalized_contrasts
        ),
        "grouping_summary": clean_string(
            result.get(
                "grouping_summary"
            )
        ),
        "evidence_limit": (
            "기사 제목과 RSS 설명을 기반으로 "
            "생성된 언론사별 분석 결과 기준"
        ),
        "grouping_status": "success",
        "grouped_at": datetime.now(
            timezone.utc
        ).isoformat(),
        "model": MODEL_NAME,
    }


def group_publishers(
    client: OpenAI,
    publisher_analyses: list[dict],
) -> dict:
    """
    동일 이슈의 언론사별 Structured Output을
    보도 경향 그룹으로 묶는다.
    """
    normalized_analyses = (
        normalize_grouping_analyses(
            publisher_analyses
        )
    )

    issue_id = normalized_analyses[
        0
    ]["issue_id"]

    prompt = build_grouping_prompt(
        issue_id=issue_id,
        publisher_analyses=(
            normalized_analyses
        ),
    )

    last_error = None

    for attempt in range(
        1,
        MAX_RETRIES + 1,
    ):
        try:
            print(
                "[Publisher Grouping] "
                f"{attempt}/{MAX_RETRIES}"
            )

            raw_result = request_solar_analysis(
                client=client,
                prompt=prompt,
            )

            validated_result = (
                validate_grouping_result(
                    result=raw_result,
                    issue_id=issue_id,
                    publisher_analyses=(
                        normalized_analyses
                    ),
                )
            )

            print(
                "[그룹화 완료] "
                f"{validated_result['group_count']}개 그룹"
            )

            return validated_result

        except Exception as error:
            last_error = error

            print(
                "[그룹화 실패] "
                f"{attempt}/{MAX_RETRIES}: "
                f"{error}"
            )

            if attempt < MAX_RETRIES:
                time.sleep(
                    RETRY_WAIT_SECONDS
                )

    raise RuntimeError(
        "Publisher Grouping이 "
        f"{MAX_RETRIES}회 모두 실패했습니다: "
        f"{last_error}"
    )

def _analyze_issue_batch_impl(
    input_data: dict,
    use_cache: bool = True,
) -> dict:
    """
    B팀이 전달한 이슈별 publishers 배열을 순회하며
    각 언론사를 독립적으로 분석하고,
    완료된 결과로 Publisher Grouping을 실행한다.
    """
    issue_id = clean_string(
        input_data.get("issue_id")
    )

    issue_title = clean_string(
        input_data.get("issue_title")
    )

    query = clean_string(
        input_data.get("query")
    )

    expanded_queries = clean_string_list(
        input_data.get(
            "expanded_queries",
            [],
        ),
        max_items=10,
    )

    publishers = input_data.get(
        "publishers",
        [],
    )

    if not issue_id:
        raise ValueError(
            "issue_id가 없습니다."
        )

    if not issue_title:
        raise ValueError(
            "issue_title이 없습니다."
        )

    if not isinstance(publishers, list):
        raise ValueError(
            "publishers는 배열이어야 합니다."
        )

    if len(publishers) < 2:
        raise ValueError(
            "분석 가능한 언론사가 2개 미만입니다."
        )

    client = create_client()

    publisher_analyses = []
    failed_publishers = []
    valid_publisher_items = []

    for index, publisher_item in enumerate(
        publishers,
        start=1,
    ):
        if not isinstance(
            publisher_item,
            dict,
        ):
            failed_publishers.append(
                {
                    "publisher_id": "",
                    "publisher": "",
                    "error": (
                        f"publishers[{index - 1}]이 "
                        "객체가 아닙니다."
                    ),
                }
            )
            continue

        publisher_id = clean_string(
            publisher_item.get(
                "publisher_id"
            )
        )

        publisher = clean_string(
            publisher_item.get(
                "publisher"
            )
        )

        articles = publisher_item.get(
            "articles",
            [],
        )

        if not publisher_id or not publisher:
            failed_publishers.append(
                {
                    "publisher_id": (
                        publisher_id
                    ),
                    "publisher": publisher,
                    "error": (
                        "publisher_id 또는 "
                        "publisher가 없습니다."
                    ),
                }
            )
            continue

        if not isinstance(articles, list):
            failed_publishers.append(
                {
                    "publisher_id": (
                        publisher_id
                    ),
                    "publisher": publisher,
                    "error": (
                        "articles가 배열이 아닙니다."
                    ),
                }
            )
            continue

        if not articles:
            print(
                f"[분석 제외] {publisher}: "
                "대표 기사가 없습니다."
            )
            continue

        valid_publisher_items.append(
            {
                "publisher_id": publisher_id,
                "publisher": publisher,
                "articles": articles,
            }
        )

    with ThreadPoolExecutor(
        max_workers=max(
            len(valid_publisher_items),
            1,
        ),
    ) as executor:
        future_to_item = {
            executor.submit(
                analyze_publisher,
                client=client,
                issue_id=issue_id,
                issue_title=issue_title,
                publisher_id=item["publisher_id"],
                publisher=item["publisher"],
                articles=item["articles"],
                use_cache=use_cache,
            ): item
            for item in valid_publisher_items
        }

        for future in as_completed(future_to_item):
            item = future_to_item[future]

            try:
                result = future.result()

                publisher_analyses.append(
                    result
                )

            except Exception as error:
                print(
                    f"[언론사 분석 실패] "
                    f"{item['publisher']}: {error}"
                )

                failed_publishers.append(
                    {
                        "publisher_id": (
                            item["publisher_id"]
                        ),
                        "publisher": item["publisher"],
                        "error": str(error),
                    }
                )

    if len(publisher_analyses) < 2:
        raise RuntimeError(
            "정상 분석된 언론사가 2개 미만이어서 "
            "Publisher Grouping을 실행할 수 없습니다."
        )

    grouping_result = group_publishers(
        client=client,
        publisher_analyses=(
            publisher_analyses
        ),
    )

    return {
        "issue_id": issue_id,
        "issue_title": issue_title,
        "query": query,
        "expanded_queries": (
            expanded_queries
        ),
        "publisher_count": len(
            publisher_analyses
        ),
        "publisher_analyses": (
            publisher_analyses
        ),
        "publisher_grouping": (
            grouping_result
        ),
        "failed_publishers": (
            failed_publishers
        ),
        "analysis_status": (
            "partial_success"
            if failed_publishers
            else "success"
        ),
        "processed_at": datetime.now(
            timezone.utc
        ).isoformat(),
    }
    

def analyze_issue_batch(
    input_data: dict,
    use_cache: bool = True,
) -> dict:
    """
    동일한 이슈 분석 요청을 하나의 실행 작업으로 병합한다.

    1. 같은 Python 프로세스에서는 threading 기반으로 병합한다.
    2. 서로 다른 Vercel 인스턴스에서는 Upstash Redis로 병합한다.
    3. 반환값은 기존 _analyze_issue_batch_impl()의 dict를 그대로 사용한다.
    """
    single_flight_key = (
        build_issue_single_flight_key(
            input_data
        )
    )

    with _SINGLE_FLIGHT_LOCK:
        current_job = (
            _SINGLE_FLIGHT_JOBS.get(
                single_flight_key
            )
        )

        if current_job is None:
            current_job = {
                "event": threading.Event(),
                "result": None,
                "error": None,
            }

            _SINGLE_FLIGHT_JOBS[
                single_flight_key
            ] = current_job

            is_local_owner = True
        else:
            is_local_owner = False

    if not is_local_owner:
        print(
            "[요청 병합] 같은 인스턴스의 "
            "선행 분석 완료 대기"
        )

        current_job["event"].wait()

        if current_job["error"] is not None:
            raise RuntimeError(
                "동일 이슈 분석의 선행 작업이 "
                "실패했습니다."
            ) from current_job["error"]

        shared_result = current_job[
            "result"
        ]

        if not isinstance(
            shared_result,
            dict,
        ):
            raise RuntimeError(
                "동일 이슈 분석의 공유 결과가 "
                "없습니다."
            )

        print(
            "[요청 병합] 같은 인스턴스의 "
            "완료 결과 재사용"
        )

        return shared_result

    try:
        if not is_distributed_single_flight_enabled():
            result = _analyze_issue_batch_impl(
                input_data=input_data,
                use_cache=use_cache,
            )

            current_job["result"] = result
            return result

        lock_key, result_key = (
            build_distributed_single_flight_keys(
                single_flight_key
            )
        )

        owner_token = uuid.uuid4().hex

        redis_errors = (
            requests.RequestException,
            json.JSONDecodeError,
            RuntimeError,
            ValueError,
        )

        if not use_cache:
            try:
                execute_redis_command(
                    "DEL",
                    result_key,
                )
            except redis_errors as redis_error:
                print(
                    "[분산 요청 병합] 기존 결과 삭제 실패: "
                    f"{redis_error}"
                )

        if use_cache:
            try:
                existing_result = (
                    get_distributed_result(
                        result_key
                    )
                )
            except redis_errors as redis_error:
                print(
                    "[분산 요청 병합] Redis 결과 조회 실패, "
                    "기존 분석 방식으로 진행: "
                    f"{redis_error}"
                )

                result = _analyze_issue_batch_impl(
                    input_data=input_data,
                    use_cache=use_cache,
                )

                current_job["result"] = result
                return result

            if existing_result is not None:
                print(
                    "[분산 요청 병합] Redis 완료 결과 재사용"
                )

                current_job[
                    "result"
                ] = existing_result

                return existing_result

        while True:
            try:
                is_distributed_owner = (
                    try_acquire_distributed_lock(
                        lock_key=lock_key,
                        owner_token=owner_token,
                    )
                )
            except redis_errors as redis_error:
                print(
                    "[분산 요청 병합] Redis lock 획득 실패, "
                    "기존 분석 방식으로 진행: "
                    f"{redis_error}"
                )

                result = _analyze_issue_batch_impl(
                    input_data=input_data,
                    use_cache=use_cache,
                )

                current_job["result"] = result
                return result

            if is_distributed_owner:
                print(
                    "[분산 요청 병합] 분산 lock 획득, "
                    "분석 시작"
                )

                try:
                    result = _analyze_issue_batch_impl(
                        input_data=input_data,
                        use_cache=use_cache,
                    )

                    try:
                        save_distributed_result(
                            result_key=result_key,
                            result=result,
                        )
                    except redis_errors as redis_error:
                        print(
                            "[분산 요청 병합] 결과 저장 실패: "
                            f"{redis_error}"
                        )

                    current_job["result"] = result
                    return result

                finally:
                    try:
                        release_distributed_lock(
                            lock_key=lock_key,
                            owner_token=owner_token,
                        )
                    except redis_errors as redis_error:
                        print(
                            "[분산 요청 병합] lock 해제 실패: "
                            f"{redis_error}"
                        )

            print(
                "[분산 요청 병합] 다른 인스턴스의 "
                "선행 분석 완료 대기"
            )

            try:
                shared_result = (
                    wait_for_distributed_result(
                        lock_key=lock_key,
                        result_key=result_key,
                    )
                )
            except TimeoutError:
                print(
                    "[분산 요청 병합] 대기 시간 초과, "
                    "lock 재획득 시도"
                )
                continue
            except redis_errors as redis_error:
                print(
                    "[분산 요청 병합] Redis 대기 실패, "
                    "기존 분석 방식으로 진행: "
                    f"{redis_error}"
                )

                result = _analyze_issue_batch_impl(
                    input_data=input_data,
                    use_cache=use_cache,
                )

                current_job["result"] = result
                return result

            if shared_result is not None:
                print(
                    "[분산 요청 병합] 다른 인스턴스의 "
                    "완료 결과 재사용"
                )

                current_job[
                    "result"
                ] = shared_result

                return shared_result

            print(
                "[분산 요청 병합] 선행 작업 결과 없음, "
                "lock 재획득 시도"
            )

    except Exception as error:
        current_job["error"] = error
        raise

    finally:
        current_job["event"].set()

        with _SINGLE_FLIGHT_LOCK:
            _SINGLE_FLIGHT_JOBS.pop(
                single_flight_key,
                None,
            )


def parse_arguments() -> argparse.Namespace:
    """
    명령행 실행 옵션을 정의한다.
    """
    parser = argparse.ArgumentParser(
        description=(
            "언론사 한 곳의 대표 기사를 "
            "Solar로 분석합니다."
        )
    )

    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT_PATH,
        help=(
            "분석할 대표 기사 JSON 파일 경로"
        ),
    )

    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help=(
            "분석 결과 JSON 파일 경로"
        ),
    )

    parser.add_argument(
        "--no-cache",
        action="store_true",
        help=(
            "기존 캐시를 사용하지 않고 "
            "Solar를 다시 호출합니다."
        ),
    )

    return parser.parse_args()


def main() -> None:
    """
    analysis.py 단독 실행 진입점.
    """
    args = parse_arguments()

    input_data = load_json(
        args.input
    )

    result = analyze_input_data(
        input_data=input_data,
        use_cache=not args.no_cache,
    )

    output_data = {
        "publisher_analyses": [
            result
        ]
    }

    save_json(
        args.output,
        output_data,
    )

    print(
        f"분석 결과를 저장했습니다: "
        f"{args.output}"
    )


if __name__ == "__main__":
    main()