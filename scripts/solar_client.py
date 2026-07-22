"""
Solar(Upstage) API 호출에 공통으로 쓰이는 클라이언트 생성, 응답 파싱,
재시도 대기시간, 문자열 정리 유틸을 모아둔 모듈.

analysis.py/compare.py가 프롬프트와 검증 로직만 다르고 클라이언트
생성·재시도·응답 파싱·문자열 정리는 거의 그대로 복사해서 각자 갖고
있었다. 프롬프트처럼 스크립트마다 실제로 달라지는 부분은 그대로
각 파일에 남기고, Solar 호출 자체에 필요한 배관만 여기로 합쳤다.
"""

from __future__ import annotations

import json
import os
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI, RateLimitError


MODEL_NAME = "solar-pro3"
REQUEST_TIMEOUT_SECONDS = 60
MAX_RETRIES = 3
RETRY_WAIT_SECONDS = 2

# 429(과다 요청)는 일반 오류와 다르게, 빨리 재시도할수록 다시 막힐
# 확률이 높다. 트래픽이 몰릴 때 재시도 간격을 시도 횟수에 비례해
# 늘려서 Upstage 쪽이 숨 돌릴 시간을 준다.
RATE_LIMIT_WAIT_SECONDS = 10


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


def wait_seconds_for_retry(
    error: Exception,
    attempt: int,
) -> int:
    """
    에러 종류에 따라 재시도 전 대기 시간을 정한다.
    레이트리밋(429)이면 더 길게, 그 외에는 기존과 동일하게 대기한다.
    """
    if isinstance(error, RateLimitError):
        return RATE_LIMIT_WAIT_SECONDS * attempt

    return RETRY_WAIT_SECONDS


def request_solar_completion(
    client: OpenAI,
    prompt: str,
    *,
    empty_error: str = "Solar 응답 내용이 비어 있습니다.",
    decode_error: str = "Solar 응답을 JSON으로 해석할 수 없습니다.",
    type_error: str = "Solar 응답이 JSON 객체가 아닙니다.",
) -> dict:
    """
    Solar API를 호출하고 JSON 응답을 파싱한다.

    호출부마다 에러 문구만 다르게 쓰고 싶을 때는 empty_error/decode_error/
    type_error를 넘겨서 맥락에 맞는 문구를 유지할 수 있다(예: compare.py는
    "Solar 비교 결과가 ..." 형태로 씀).
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
        raise ValueError(empty_error)

    try:
        result = json.loads(content)

    except json.JSONDecodeError as error:
        raise ValueError(decode_error) from error

    if not isinstance(result, dict):
        raise ValueError(type_error)

    return result
