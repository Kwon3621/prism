#공통 내용
#핵심 관점
#강조된 원인·배경
#강조한 영향·대상
#보도 태도와 근거
#원문 링크

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from openai import OpenAI

from cache import (
    get_comparison,
    save_comparison,
)
from solar_client import (
    MAX_RETRIES,
    MODEL_NAME,
    REQUEST_TIMEOUT_SECONDS,
    clean_string,
    clean_string_list,
    create_client,
    request_solar_completion,
    wait_seconds_for_retry,
)


DEFAULT_INPUT_PATH = Path(
    "data/publisher_analyses.json"
)
DEFAULT_OUTPUT_PATH = Path(
    "data/comparison_result.json"
)

ALLOWED_DIMENSIONS = {
    "공통 내용",
    "핵심 관점",
    "강조된 원인·배경",
    "강조한 영향·대상",
    "보도 태도·근거",
}

# 이슈 하나에 들어올 수 있는 최대 언론사 수(issue_builder.py의
# DEFAULT_PUBLISHER_LIMIT과 동일). 상세 대조표는 UI상 최대 4개까지만
# 선택하게 해뒀지만(app.js:initPublisherSelector), 이슈 전체 언론사
# 기준 "공통 내용 요약"은 4개로 자르지 않고 이 상한까지 전부 보낸다.
MAX_PUBLISHERS = 6

# evidence(판단 근거)는 "보도 태도·근거" 항목에만 붙인다 — 원래 의도가
# "왜 그렇게 판단했는지" 근거가 필요한 건 보도 태도뿐이었는데, 한때
# 4개 항목 모두에 evidence를 요구·표시하게 만들어서 비교 항목 전체에
# 근거 문구가 달리는 문제가 있었다.
EVIDENCE_REQUIRED_DIMENSION = "보도 태도·근거"

ALLOWED_DIFFERENCE_LEVELS = {
    "차이 큼",
    "일부 차이",
    "유사함",
    "판단 어려움",
}


def load_json(path: Path) -> dict:
    """
    UTF-8 JSON 파일을 읽는다.
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
            "JSON 최상위 값은 객체여야 합니다."
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


def normalize_text_for_duplicate_check(value: Any) -> str:
    """공백만 제거해서 비교한다 (summary가 기사 제목을 그대로 복사했는지
    확인하는 용도라, 구두점까지 봐줄 필요는 없다)."""
    return "".join(str(value or "").split())


def normalize_publisher_analyses(
    values: Any,
) -> list[dict]:
    """
    analysis.py가 만든 언론사별 분석 결과를 검증하고 정리한다.
    """
    if not isinstance(values, list):
        raise ValueError(
            "publisher_analyses는 배열이어야 합니다."
        )

    if len(values) < 2:
        raise ValueError(
            "비교하려면 최소 2개 언론사가 필요합니다."
        )

    if len(values) > MAX_PUBLISHERS:
        raise ValueError(
            f"한 번에 최대 {MAX_PUBLISHERS}개 언론사만 비교할 수 있습니다."
        )

    normalized = []
    seen_publishers = set()
    issue_ids = set()

    for index, item in enumerate(values):
        if not isinstance(item, dict):
            raise ValueError(
                f"publisher_analyses[{index}]는 "
                "객체여야 합니다."
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
        articles = item.get("articles", [])

        if not issue_id:
            raise ValueError(
                f"{index + 1}번째 결과에 "
                "issue_id가 없습니다."
            )

        if not publisher_id:
            raise ValueError(
                f"{index + 1}번째 결과에 "
                "publisher_id가 없습니다."
            )

        if not publisher:
            raise ValueError(
                f"{index + 1}번째 결과에 "
                "publisher가 없습니다."
            )

        if not isinstance(analysis, dict):
            raise ValueError(
                f"{publisher}의 analysis가 "
                "객체가 아닙니다."
            )

        if publisher_id in seen_publishers:
            raise ValueError(
                f"언론사가 중복되었습니다: "
                f"{publisher_id}"
            )

        if not isinstance(articles, list):
            articles = []

        seen_publishers.add(
            publisher_id
        )
        issue_ids.add(issue_id)

        normalized.append(
            {
                "issue_id": issue_id,
                "publisher_id": publisher_id,
                "publisher": publisher,
                "articles": articles,
                "analysis": analysis,
            }
        )

    if len(issue_ids) != 1:
        raise ValueError(
            "서로 다른 이슈의 분석 결과는 "
            "함께 비교할 수 없습니다."
        )

    return normalized


def build_analysis_text(
    publisher_analyses: list[dict],
) -> str:
    """
    언론사별 Structured Output을
    Solar 비교 프롬프트용 텍스트로 변환한다.
    """
    sections = []

    for item in publisher_analyses:
        analysis = item["analysis"]

        sections.append(
            f"""
언론사 ID: {item["publisher_id"]}
언론사명: {item["publisher"]}

공통 기사 요약:
{analysis.get("article_summary", "")}

제목 프레임:
{analysis.get("headline_frame", "")}

핵심 관점:
{analysis.get("main_focus", "")}

핵심 키워드:
{json.dumps(
    analysis.get("keywords", []),
    ensure_ascii=False
)}

주요 행위자:
{json.dumps(
    analysis.get("main_actors", []),
    ensure_ascii=False
)}

인용 대상:
{json.dumps(
    analysis.get("quoted_sources", []),
    ensure_ascii=False
)}

강조된 원인:
{json.dumps(
    analysis.get("causes", []),
    ensure_ascii=False
)}

강조된 배경:
{json.dumps(
    analysis.get("background", []),
    ensure_ascii=False
)}

강조된 영향:
{json.dumps(
    analysis.get("emphasized_effects", []),
    ensure_ascii=False
)}

영향 대상:
{json.dumps(
    analysis.get("affected_groups", []),
    ensure_ascii=False
)}

보도 태도:
{json.dumps(
    analysis.get("tone", {}),
    ensure_ascii=False
)}

상대적으로 적게 다룬 맥락:
{json.dumps(
    analysis.get("less_covered_context", []),
    ensure_ascii=False
)}

기사 및 원문 링크:
{json.dumps(
    item.get("articles", []),
    ensure_ascii=False
)}
""".strip()
        )

    return "\n\n====================\n\n".join(
        sections
    )


def build_comparison_prompt(
    issue_id: str,
    publisher_analyses: list[dict],
) -> str:
    """
    선택된 언론사 분석 결과를 비교하기 위한
    Solar 프롬프트를 생성한다.
    """
    analysis_text = build_analysis_text(
        publisher_analyses
    )

    publisher_names = [
        item["publisher"]
        for item in publisher_analyses
    ]

    return f"""
당신은 뉴스 기사 비교 서비스 Prism의
선택 언론사 비교 분석기입니다.

현재 입력은 기사 원문이 아니라,
각 언론사의 대표 기사를 독립적으로 분석한
Structured Output입니다.

이슈 ID:
{issue_id}

선택 언론사:
{", ".join(publisher_names)}

비교 원칙:
- 입력된 분석 결과에서 확인되는 내용만 사용하세요.
- 기사 원문 전체를 읽은 것처럼 작성하지 마세요.
- 언론사의 고정된 정치 성향을 판단하지 마세요.
- 기자나 언론사의 의도를 추측하지 마세요.
- 표현이 다르다는 이유만으로 관점 차이를 과장하지 마세요.
- 실제 차이가 작으면 "유사함"으로 판단하세요.
- 분석 근거가 부족하면 "판단 어려움"으로 작성하세요.
- 각 비교 문장은 어느 언론사가 무엇을 강조했는지
  직접 대조하는 형태로 작성하세요.
- 공통 사실과 언론사별 차이를 구분하세요.
- evidence는 "보도 태도·근거" 항목에만 작성하세요. 그 외 4개 항목
  (공통 내용/핵심 관점/강조된 원인·배경/강조한 영향·대상)의
  publisher_details에는 evidence를 넣지 말고 summary만 작성하세요.
- "보도 태도·근거" 항목의 evidence는 언론사별로 최소 1개 이상 반드시
  채우세요. summary만 쓰고 evidence를 비워두지 마세요. 그 언론사에
  대한 근거를 정말 찾을 수 없을 때만 evidence를 비워도 되며, 그 경우
  해당 비교 항목의 difference_level을 "판단 어려움"으로 쓰세요.
- summary와 evidence의 역할을 분리하세요. summary에는 기사 제목이나
  RSS 설명 문구를 그대로 옮기지 말고, 그 언론사가 무엇을 강조했는지
  또는 어떤 태도를 보였는지를 한 문장으로 설명하세요. 실제 기사
  제목·인용구 같은 구체적 표현은 "보도 태도·근거"의 evidence에만
  넣으세요.
- 원문 링크는 입력된 기사 정보에서만 가져오세요.
- source_links의 title, link, published_at은 입력된 기사 정보를 그대로 복사하세요.
- 입력 기사의 published_at 값이 "발행 시간 정보 없음"이면 그대로 출력하세요.
- 발행 시간을 추측하거나 임의로 생성하지 마세요.
- JSON 이외의 문장은 출력하지 마세요.

비교 항목은 반드시 다음 5개를 포함하세요.

1. 공통 내용
2. 핵심 관점
3. 강조된 원인·배경
4. 강조한 영향·대상
5. 보도 태도·근거

comparisons 배열에는 반드시 위 5개 항목이 각각 하나씩, 총 5개의 원소로
포함되어야 합니다. 1개만 작성하고 끝내지 마세요.

difference_level은 다음 중 하나만 사용하세요.

- 차이 큼
- 일부 차이
- 유사함
- 판단 어려움

반드시 아래 JSON 구조로만 응답하세요.

{{
  "issue_id": "{issue_id}",
  "selected_publishers": [
    {{
      "publisher_id": "언론사 ID",
      "publisher": "언론사명"
    }}
  ],
  "common_summary": "선택 언론사에서 공통적으로 확인되는 내용을 1~3문장으로 요약",
  "overall_difference": "차이 큼 또는 일부 차이 또는 유사함 또는 판단 어려움",
  "comparisons": [
    {{
      "dimension": "공통 내용",
      "difference_level": "차이 정도",
      "contrast_statement": "언론사별 공통점 또는 차이를 직접 대조하는 문장",
      "publisher_details": [
        {{
          "publisher_id": "언론사 ID",
          "publisher": "언론사명",
          "summary": "이 항목에서 해당 언론사가 강조한 내용"
        }}
      ]
    }},
    {{
      "dimension": "핵심 관점",
      "difference_level": "차이 정도",
      "contrast_statement": "언론사별 공통점 또는 차이를 직접 대조하는 문장",
      "publisher_details": [
        {{
          "publisher_id": "언론사 ID",
          "publisher": "언론사명",
          "summary": "이 항목에서 해당 언론사가 강조한 내용"
        }}
      ]
    }},
    {{
      "dimension": "강조된 원인·배경",
      "difference_level": "차이 정도",
      "contrast_statement": "언론사별 공통점 또는 차이를 직접 대조하는 문장",
      "publisher_details": [
        {{
          "publisher_id": "언론사 ID",
          "publisher": "언론사명",
          "summary": "이 항목에서 해당 언론사가 강조한 내용"
        }}
      ]
    }},
    {{
      "dimension": "강조한 영향·대상",
      "difference_level": "차이 정도",
      "contrast_statement": "언론사별 공통점 또는 차이를 직접 대조하는 문장",
      "publisher_details": [
        {{
          "publisher_id": "언론사 ID",
          "publisher": "언론사명",
          "summary": "이 항목에서 해당 언론사가 강조한 내용"
        }}
      ]
    }},
    {{
      "dimension": "보도 태도·근거",
      "difference_level": "차이 정도",
      "contrast_statement": "언론사별 공통점 또는 차이를 직접 대조하는 문장",
      "publisher_details": [
        {{
          "publisher_id": "언론사 ID",
          "publisher": "언론사명",
          "summary": "이 언론사가 보인 보도 태도를 한 문장으로 설명 (기사 제목·인용구 인용 금지, 예: '사실관계를 중립적으로 전달함')",
          "evidence": [
            "그 태도를 판단한 실제 제목·설명 표현"
          ]
        }}
      ]
    }}
  ],
  "similarities": [
    "선택 언론사에서 공통적으로 나타난 내용"
  ],
  "key_differences": [
    "가장 중요한 차이"
  ],
  "comparison_report": "공통 내용, 핵심 관점, 원인·배경, 영향·대상, 보도 태도를 종합한 자연스러운 비교 리포트",
  "source_links": [
    {{
      "publisher_id": "언론사 ID",
      "publisher": "언론사명",
      "title": "기사 제목",
      "link": "원문 링크",
      "published_at": "기사 발행 시간"
    }}
  ],
  "evidence_limit": "기사 제목과 RSS 설명을 기반으로 생성된 언론사별 분석 결과 기준"
}}

언론사별 Structured Output:

{analysis_text}
""".strip()


def request_solar_comparison(
    client: OpenAI,
    prompt: str,
) -> dict:
    """
    Solar API를 호출하고 JSON 결과를 반환한다.
    (실제 호출·파싱 로직은 solar_client.request_solar_completion 참고 —
    analysis.py의 request_solar_analysis와 거의 동일했던 걸 통합했다.)
    """
    return request_solar_completion(
        client,
        prompt,
        empty_error="Solar 비교 결과가 비어 있습니다.",
        decode_error="Solar 비교 결과를 JSON으로 해석할 수 없습니다.",
        type_error="Solar 비교 결과가 JSON 객체가 아닙니다.",
    )


def collect_source_links(
    publisher_analyses: list[dict],
) -> list[dict]:
    """
    언론사별 분석 결과에 포함된 기사 원문 링크를 수집한다.
    """
    links = []
    seen = set()

    for item in publisher_analyses:
        for article in item.get(
            "articles",
            [],
        ):
            if not isinstance(article, dict):
                continue

            link = clean_string(
                article.get("link")
            )

            title = clean_string(
                article.get("title")
            )

            published_at = clean_string(
                article.get("published_at")
            )

            if not link:
                continue

            if link in seen:
                continue

            seen.add(link)

            links.append(
                {
                    "publisher_id": (
                        item["publisher_id"]
                    ),
                    "publisher": (
                        item["publisher"]
                    ),
                    "title": title,
                    "link": link,
                    "published_at": published_at,
                }
            )

    return links


def validate_comparison_result(
    result: Any,
    issue_id: str,
    publisher_analyses: list[dict],
) -> dict:
    """
    Solar 비교 결과를 고정 JSON 구조로 검증하고 정리한다.
    """
    if not isinstance(result, dict):
        raise ValueError(
            "비교 결과의 최상위 값이 "
            "객체가 아닙니다."
        )

    selected_publishers = [
        {
            "publisher_id": (
                item["publisher_id"]
            ),
            "publisher": item["publisher"],
        }
        for item in publisher_analyses
    ]

    expected_publisher_ids = {
        item["publisher_id"]
        for item in publisher_analyses
    }

    comparisons = result.get(
        "comparisons",
        [],
    )

    if not isinstance(comparisons, list):
        raise ValueError(
            "comparisons는 배열이어야 합니다."
        )

    normalized_comparisons = []
    returned_dimensions = set()

    for comparison in comparisons:
        if not isinstance(comparison, dict):
            continue

        dimension = clean_string(
            comparison.get("dimension")
        )

        if dimension not in ALLOWED_DIMENSIONS:
            continue

        if dimension in returned_dimensions:
            continue

        difference_level = clean_string(
            comparison.get(
                "difference_level"
            )
        )

        if (
            difference_level
            not in ALLOWED_DIFFERENCE_LEVELS
        ):
            difference_level = (
                "판단 어려움"
            )

        details = comparison.get(
            "publisher_details",
            [],
        )

        if not isinstance(details, list):
            details = []

        normalized_details = []
        seen_detail_publishers = set()

        for detail in details:
            if not isinstance(detail, dict):
                continue

            publisher_id = clean_string(
                detail.get("publisher_id")
            )

            if (
                publisher_id
                not in expected_publisher_ids
            ):
                continue

            if (
                publisher_id
                in seen_detail_publishers
            ):
                continue

            source_item = next(
                item
                for item in publisher_analyses
                if item["publisher_id"]
                == publisher_id
            )

            seen_detail_publishers.add(
                publisher_id
            )

            normalized_details.append(
                {
                    "publisher_id": (
                        publisher_id
                    ),
                    "publisher": (
                        source_item[
                            "publisher"
                        ]
                    ),
                    "summary": clean_string(
                        detail.get("summary")
                    ),
                    # evidence는 "보도 태도·근거" 항목에만 붙인다. 다른
                    # 항목까지 evidence를 들고 있으면 app.js가 화면에
                    # 그대로 노출해버려서, 여기서 아예 비워 전달한다.
                    "evidence": (
                        clean_string_list(
                            detail.get(
                                "evidence"
                            ),
                            max_items=5,
                        )
                        if dimension
                        == EVIDENCE_REQUIRED_DIMENSION
                        else []
                    ),
                }
            )

        if dimension == EVIDENCE_REQUIRED_DIMENSION:
            for detail in normalized_details:
                # difference_level이 "판단 어려움"이 아니라면, 그 판단에
                # 쓰인 evidence가 언론사마다 최소 1개는 있어야 한다.
                # summary(태도)만 쓰고 evidence를 비워두는 응답을 여기서
                # 걸러 재시도시킨다.
                if (
                    difference_level != "판단 어려움"
                    and not detail["evidence"]
                ):
                    raise ValueError(
                        f"'{dimension}' 항목의 "
                        f"{detail['publisher']} evidence가 "
                        "비어 있습니다."
                    )

                # summary는 "이 언론사가 보인 태도"를 설명해야지, 기사
                # 제목을 그대로 옮겨서는 안 된다(프롬프트에 명시했지만
                # 실측 결과 모델이 종종 어김 — summary와 evidence가
                # 그대로 중복 노출되는 문제로 이어짐). 원본 기사 제목과
                # 완전히 같으면 재시도시킨다.
                source_item = next(
                    item
                    for item in publisher_analyses
                    if item["publisher_id"]
                    == detail["publisher_id"]
                )

                source_titles = {
                    normalize_text_for_duplicate_check(
                        article.get("title")
                    )
                    for article in source_item.get(
                        "articles",
                        [],
                    )
                }

                if (
                    normalize_text_for_duplicate_check(
                        detail["summary"]
                    )
                    in source_titles
                ):
                    raise ValueError(
                        f"'{dimension}' 항목의 "
                        f"{detail['publisher']} summary가 "
                        "기사 제목을 그대로 복사했습니다."
                    )

        normalized_comparisons.append(
            {
                "dimension": dimension,
                "difference_level": (
                    difference_level
                ),
                "contrast_statement": (
                    clean_string(
                        comparison.get(
                            "contrast_statement"
                        )
                    )
                ),
                "publisher_details": (
                    normalized_details
                ),
            }
        )

        returned_dimensions.add(
            dimension
        )

    missing_dimensions = (
        ALLOWED_DIMENSIONS
        - returned_dimensions
    )

    # Solar가 5개 항목 중 1개만 채워서 응답하는 등 대부분의 비교 항목을
    # 통째로 누락시키면, 빈 자리를 채우는 대신 재시도하도록 실패시킨다.
    # (1개 정도의 누락은 group_publishers와 마찬가지로 아래에서 자리만
    # 채워서 복구한다.)
    if len(missing_dimensions) > 1:
        raise ValueError(
            "비교 항목이 대부분 누락되었습니다: "
            f"{sorted(missing_dimensions)}"
        )

    for dimension in [
        "공통 내용",
        "핵심 관점",
        "강조된 원인·배경",
        "강조한 영향·대상",
        "보도 태도·근거",
    ]:
        if dimension not in missing_dimensions:
            continue

        normalized_comparisons.append(
            {
                "dimension": dimension,
                "difference_level": (
                    "판단 어려움"
                ),
                "contrast_statement": (
                    "제공된 분석 결과만으로 "
                    "명확한 비교가 어렵습니다."
                ),
                "publisher_details": [],
            }
        )

    overall_difference = clean_string(
        result.get("overall_difference")
    )

    if (
        overall_difference
        not in ALLOWED_DIFFERENCE_LEVELS
    ):
        overall_difference = (
            "판단 어려움"
        )

    normalized_result = {
        "issue_id": issue_id,
        "selected_publishers": (
            selected_publishers
        ),
        "common_summary": clean_string(
            result.get("common_summary")
        ),
        "overall_difference": (
            overall_difference
        ),
        "comparisons": (
            normalized_comparisons
        ),
        "similarities": clean_string_list(
            result.get("similarities"),
            max_items=8,
        ),
        "key_differences": (
            clean_string_list(
                result.get(
                    "key_differences"
                ),
                max_items=8,
            )
        ),
        "comparison_report": (
            clean_string(
                result.get(
                    "comparison_report"
                )
            )
        ),
        "source_links": (
            collect_source_links(
                publisher_analyses
            )
        ),
        "evidence_limit": (
            "기사 제목과 RSS 설명을 기반으로 "
            "생성된 언론사별 분석 결과 기준"
        ),
        "comparison_status": "success",
        "compared_at": datetime.now(
            timezone.utc
        ).isoformat(),
        "model": MODEL_NAME,
    }

    if not normalized_result[
        "common_summary"
    ]:
        raise ValueError(
            "common_summary가 비어 있습니다."
        )

    if not normalized_result[
        "comparison_report"
    ]:
        raise ValueError(
            "comparison_report가 비어 있습니다."
        )

    return normalized_result


def compare_publishers(
    client: OpenAI,
    publisher_analyses: list[dict],
    use_cache: bool = True,
) -> dict:
    """
    선택된 2~MAX_PUBLISHERS개 언론사의 분석 결과를 비교한다.
    """
    normalized_analyses = (
        normalize_publisher_analyses(
            publisher_analyses
        )
    )

    issue_id = normalized_analyses[
        0
    ]["issue_id"]

    publisher_ids = [
        item["publisher_id"]
        for item in normalized_analyses
    ]

    if use_cache:
        cached_result = get_comparison(
            issue_id=issue_id,
            publisher_ids=publisher_ids,
        )

        if cached_result:
            print(
                "[캐시 사용] 선택 언론사 "
                "비교 결과"
            )

            return cached_result

    prompt = build_comparison_prompt(
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
                "[Solar 비교] "
                f"{attempt}/{MAX_RETRIES}"
            )

            raw_result = (
                request_solar_comparison(
                    client=client,
                    prompt=prompt,
                )
            )

            validated_result = (
                validate_comparison_result(
                    result=raw_result,
                    issue_id=issue_id,
                    publisher_analyses=(
                        normalized_analyses
                    ),
                )
            )

            save_comparison(
                issue_id=issue_id,
                publisher_ids=publisher_ids,
                result=validated_result,
            )

            print(
                "[비교 완료] "
                + ", ".join(
                    item["publisher"]
                    for item
                    in normalized_analyses
                )
            )

            return validated_result

        except Exception as error:
            last_error = error

            print(
                "[비교 실패] "
                f"{attempt}/{MAX_RETRIES}: "
                f"{error}"
            )

            if attempt < MAX_RETRIES:
                time.sleep(
                    wait_seconds_for_retry(
                        error,
                        attempt,
                    )
                )

    raise RuntimeError(
        "언론사 비교가 "
        f"{MAX_RETRIES}회 모두 실패했습니다: "
        f"{last_error}"
    )


def analyze_input_data(
    input_data: dict,
    use_cache: bool = True,
) -> dict:
    """
    입력 JSON에서 언론사별 분석 결과를 읽고 비교한다.
    """
    publisher_analyses = input_data.get(
        "publisher_analyses",
        [],
    )

    client = create_client()

    return compare_publishers(
        client=client,
        publisher_analyses=publisher_analyses,
        use_cache=use_cache,
    )


def parse_arguments() -> argparse.Namespace:
    """
    명령행 옵션을 정의한다.
    """
    parser = argparse.ArgumentParser(
        description=(
            "언론사별 Structured Output을 "
            "비교합니다."
        )
    )

    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT_PATH,
        help=(
            "언론사별 분석 결과 JSON 경로"
        ),
    )

    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help=(
            "선택 언론사 비교 결과 저장 경로"
        ),
    )

    parser.add_argument(
        "--no-cache",
        action="store_true",
        help=(
            "기존 비교 캐시를 사용하지 않고 "
            "Solar를 다시 호출합니다."
        ),
    )

    return parser.parse_args()


def main() -> None:
    """
    compare.py 단독 실행 진입점.
    """
    args = parse_arguments()

    input_data = load_json(
        args.input
    )

    result = analyze_input_data(
        input_data=input_data,
        use_cache=not args.no_cache,
    )

    save_json(
        args.output,
        result,
    )

    print(
        "비교 결과를 저장했습니다: "
        f"{args.output}"
    )


if __name__ == "__main__":
    main()