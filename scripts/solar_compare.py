import json
import os
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI


MATCHED_CLUSTERS_PATH = Path(
    "data/matched_clusters.json"
)
OUTPUT_PATH = Path("data/issue.json")

MODEL_NAME = "solar-pro3"
REQUEST_TIMEOUT_SECONDS = 60
MAX_RETRIES = 2


def load_json(path):
    """
    JSON 파일을 읽는다.
    """
    if not path.exists():
        raise FileNotFoundError(
            f"{path} 파일이 없습니다."
        )

    with path.open(
        "r",
        encoding="utf-8",
    ) as file:
        return json.load(file)


def build_cluster_text(matched_issue):
    """
    언론사별 기사 묶음을 Solar에 전달할
    텍스트 형태로 변환한다.
    """
    cluster_sections = []

    for cluster in matched_issue.get(
        "clusters",
        [],
    ):
        publisher = cluster.get(
            "publisher",
            "언론사 미상",
        )

        articles = cluster.get(
            "articles",
            [],
        )

        article_sections = []

        for article_number, article in enumerate(
            articles,
            start=1,
        ):
            title = article.get(
                "title",
                "",
            )

            description = article.get(
                "description",
                "",
            )

            link = article.get(
                "link",
                "",
            )

            published = article.get(
                "published",
                "",
            )

            article_sections.append(
                f"""
기사 {article_number}
제목: {title}
RSS 설명: {description}
발행 정보: {published}
원문 링크: {link}
""".strip()
            )

        cluster_sections.append(
            f"""
언론사: {publisher}
이 언론사의 기사 수: {len(articles)}
언론사 내부 대표 제목: {cluster.get("topic_title", "")}

기사 목록:
{chr(10).join(article_sections)}
""".strip()
        )

    return "\n\n====================\n\n".join(
        cluster_sections
    )


def build_prompt(matched_issue):
    """
    언론사별 기사 묶음을 비교하기 위한
    Solar 프롬프트를 만든다.
    """
    issue_text = build_cluster_text(
        matched_issue
    )

    match_id = matched_issue.get(
        "match_id",
        "match-unknown",
    )

    category = matched_issue.get(
        "category",
        "기타",
    )

    return f"""
다음은 서로 다른 언론사가 동일한 사건을 보도한 것으로
판단된 언론사별 기사 묶음입니다.

각 언론사는 같은 사건을 한 개 또는 여러 개의 기사로
보도했을 수 있습니다.

현재 제공되는 자료는 기사 제목, RSS 설명, 발행 정보,
원문 링크입니다. 제공된 자료에서 확인되지 않는 내용은
추정하지 마세요.

분석 대상 ID: {match_id}
분류: {category}

분석 원칙:
- 특정 언론사가 옳거나 편향되었다고 판단하지 마세요.
- 기자 또는 언론사의 정치적 의도를 추정하지 마세요.
- 기사 제목과 RSS 설명에 실제로 나타난 내용만 분석하세요.
- 동일 언론사의 여러 기사는 하나의 보도 묶음으로 종합하세요.
- 공통 사실과 언론사별 강조 차이를 구분하세요.
- 단순히 표현이 다르다는 이유만으로 보도 관점이 다르다고
  단정하지 마세요.
- 차이가 명확하지 않다면
  "명확한 차이를 확인하기 어려움"이라고 작성하세요.
- 핵심 키워드와 주요 인물·기관은 제공된 자료에 등장한 것만
  사용하세요.
- 모든 언론사를 빠짐없이 articles 배열에 포함하세요.
- JSON 이외의 문장은 출력하지 마세요.

반드시 아래 JSON 구조로만 답하세요.

{{
  "issue_id": "{match_id}",
  "category": "{category}",
  "title": "모든 언론사의 기사를 아우르는 중립적인 사건 제목",
  "summary": "사건의 공통 내용을 설명하는 1~2문장",
  "common_facts": [
    "여러 언론사 기사에서 공통으로 확인되는 사실"
  ],
  "articles": [
    {{
      "publisher": "언론사명",
      "article_count": 1,
      "titles": [
        "해당 언론사 기사 제목"
      ],
      "links": [
        "해당 기사 원문 링크"
      ],
      "title": "대표 기사 제목 또는 대표 제목",
      "link": "대표 기사 원문 링크",
      "keywords": [
        "기사 묶음에서 확인되는 핵심 키워드"
      ],
      "people": [
        "기사 묶음에 등장한 주요 인물 또는 기관"
      ],
      "focus": "해당 언론사 기사 묶음에서 상대적으로 강조된 내용",
      "expression_summary": "제목과 RSS 설명에서 확인되는 표현 방식",
      "evidence_limit": "현재 제공된 자료만으로 판단하기 어려운 부분"
    }}
  ]
}}

언론사별 기사 묶음:

{issue_text}
""".strip()

def complete_articles(result, matched_issue):
    """
    Solar가 누락한 언론사를 원본 클러스터 데이터로 보완하고,
    article_count, titles, links, title, link는 원본 기준으로 고정한다.
    """

    solar_articles = result.get("articles", [])

    # Solar가 예상과 다른 형식을 반환하는 경우를 대비
    if not isinstance(solar_articles, list):
        solar_articles = []

    solar_by_publisher = {}

    for article in solar_articles:
        # 문자열 등 잘못된 형식은 건너뛴다.
        if not isinstance(article, dict):
            continue

        publisher = article.get("publisher")

        if not publisher:
            continue

        solar_by_publisher[publisher] = article

    completed_articles = []

    for cluster in matched_issue.get("clusters", []):
        publisher = cluster.get(
            "publisher",
            "언론사 미상",
        )

        original_articles = cluster.get(
            "articles",
            [],
        )

        titles = [
            article.get("title", "")
            for article in original_articles
            if article.get("title")
        ]

        links = [
            article.get("link", "")
            for article in original_articles
            if article.get("link")
        ]

        solar_article = solar_by_publisher.get(
            publisher,
            {},
        )

        completed_articles.append(
            {
                "publisher": publisher,
                "article_count": len(
                    original_articles
                ),
                "titles": titles,
                "links": links,
                "title": (
                    titles[0]
                    if titles
                    else cluster.get(
                        "topic_title",
                        "",
                    )
                ),
                "link": (
                    links[0]
                    if links
                    else ""
                ),
                "keywords": solar_article.get(
                    "keywords",
                    [],
                ),
                "people": solar_article.get(
                    "people",
                    [],
                ),
                "focus": solar_article.get(
                    "focus",
                    "명확한 차이를 확인하기 어려움",
                ),
                "expression_summary": (
                    solar_article.get(
                        "expression_summary",
                        "명확한 차이를 확인하기 어려움",
                    )
                ),
                "evidence_limit": solar_article.get(
                    "evidence_limit",
                    "현재 제공된 자료만으로는 "
                    "구체적인 차이를 판단하기 어려움",
                ),
            }
        )

    result["articles"] = completed_articles

    return result

def build_fallback_result(matched_issue, error_message):
    """
    Solar 재시도까지 모두 실패한 이슈를 원본 데이터로 보완한다.

    언론사명, 기사 제목, 링크 등 원본 정보는 유지하고,
    Solar 분석이 필요한 필드는 기본 안내 문구로 채운다.
    """
    match_id = matched_issue.get(
        "match_id",
        "match-unknown",
    )

    clusters = matched_issue.get(
        "clusters",
        [],
    )

    representative_title = next(
        (
            cluster.get("topic_title")
            for cluster in clusters
            if cluster.get("topic_title")
        ),
        "자동 분석에 실패한 이슈",
    )

    fallback_result = {
        "issue_id": match_id,
        "category": matched_issue.get(
            "category",
            "기타",
        ),
        "title": representative_title,
        "summary": (
            "Solar 분석 요청이 반복해서 실패하여 "
            "원본 기사 정보만 표시합니다."
        ),
        "common_facts": [],
        "articles": [],
        "analysis_status": "fallback",
        "analysis_error": str(error_message),
    }

    return complete_articles(
        fallback_result,
        matched_issue,
    )


def create_client():
    """
    환경변수에서 Upstage API 키를 읽고
    API 클라이언트를 생성한다.
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


def analyze_issue(
    client,
    matched_issue,
):
    """
    공통 이슈 하나를 Solar로 비교·분석한다.
    """
    match_id = matched_issue.get(
        "match_id",
        "match-unknown",
    )

    prompt = build_prompt(
        matched_issue
    )

    print(f"\nSolar 분석 중: {match_id}")

    response = client.chat.completions.create(
        model=MODEL_NAME,
        messages=[
            {
                "role": "user",
                "content": prompt,
            }
        ],
        response_format={
            "type": "json_object"
        },
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
            f"{match_id} 분석 결과가 비어 있습니다."
        )

    try:
        result = json.loads(content)
    except json.JSONDecodeError as error:
        raise ValueError(
            f"{match_id}의 Solar 응답을 "
            f"JSON으로 읽지 못했습니다."
        ) from error

    returned_publishers = []

    for article in result.get("articles", []):
        if isinstance(article, dict):
            returned_publishers.append(
                article.get("publisher")
            )
        else:
            returned_publishers.append(
                f"잘못된 형식: {repr(article)}"
            )

    expected_publishers = [
        cluster.get("publisher")
        for cluster in matched_issue.get(
            "clusters",
            [],
        )
    ]

    print(
        f"{match_id} 원본 언론사: "
        f"{expected_publishers}"
    )
    print(
        f"{match_id} Solar 반환 언론사: "
        f"{returned_publishers}"
    )

    missing_publishers = [
        publisher
        for publisher in expected_publishers
        if publisher not in returned_publishers
    ]

    if missing_publishers:
        print(
            f"[경고] {match_id} Solar 누락 언론사: "
            f"{missing_publishers}"
        )
    else:
        print(
            f"{match_id} 누락 언론사: 없음"
        )


    # 모델이 값을 누락하더라도 기본 식별자는 유지한다.
    result["issue_id"] = match_id
    result["category"] = result.get(
        "category"
    ) or matched_issue.get(
        "category",
        "기타"
    )

    result = complete_articles(
        result,
        matched_issue,
    )

    final_publishers = [
        article.get("publisher")
        for article in result.get("articles", [])
    ]

    print(
        f"{match_id} 최종 저장 언론사: "
        f"{final_publishers}"
    )

    print(
        f"{match_id} 처리 결과: "
        f"원본 {len(expected_publishers)}개 / "
        f"Solar {len(returned_publishers)}개 / "
        f"최종 {len(final_publishers)}개"
    )

    print(f"분석 완료: {match_id}")

    return result


def main():
    matched_data = load_json(
        MATCHED_CLUSTERS_PATH
    )

    matched_issues = matched_data.get(
        "matched_issues",
        [],
    )

    if not matched_issues:
        raise ValueError(
            "Solar로 분석할 공통 이슈가 없습니다. "
            "먼저 compare_cluster.py를 실행하세요."
        )

    client = create_client()

    print(
        f"Solar 분석 대상 공통 이슈: "
        f"{len(matched_issues)}개"
    )

    results_by_id = {}
    failed_issues = []
    last_errors = {}

    for matched_issue in matched_issues:
        match_id = matched_issue.get(
            "match_id",
            "match-unknown",
        )

        try:
            result = analyze_issue(
                client,
                matched_issue,
            )
            results_by_id[match_id] = result

        except Exception as error:
            print(
                f"[오류] {match_id} 1차 분석 실패: "
                f"{error}"
            )
            print(
                f"{match_id}를 재시도 목록에 추가합니다."
            )

            failed_issues.append(
                matched_issue
            )
            last_errors[match_id] = error

    for retry_number in range(
        1,
        MAX_RETRIES + 1,
    ):
        if not failed_issues:
            break

        print(
            f"\n실패 이슈 재시도 "
            f"{retry_number}/{MAX_RETRIES}: "
            f"{len(failed_issues)}개"
        )

        retry_targets = failed_issues
        failed_issues = []

        for matched_issue in retry_targets:
            match_id = matched_issue.get(
                "match_id",
                "match-unknown",
            )

            try:
                result = analyze_issue(
                    client,
                    matched_issue,
                )
                results_by_id[match_id] = result

                print(
                    f"{match_id} 재시도 성공"
                )

            except Exception as error:
                print(
                    f"[재시도 실패] {match_id}: "
                    f"{error}"
                )

                failed_issues.append(
                    matched_issue
                )
                last_errors[match_id] = error

    if failed_issues:
        print(
            "\n최종 분석 실패 이슈를 "
            "원본 데이터 기반 결과로 저장합니다."
        )

        for matched_issue in failed_issues:
            match_id = matched_issue.get(
                "match_id",
                "match-unknown",
            )

            error = last_errors.get(
                match_id,
                "알 수 없는 오류",
            )

            fallback_result = build_fallback_result(
                matched_issue,
                error,
            )

            results_by_id[match_id] = (
                fallback_result
            )

            print(
                f"- {match_id}: fallback 저장 완료"
            )

    results = [
        results_by_id[
            matched_issue.get(
                "match_id",
                "match-unknown",
            )
        ]
        for matched_issue in matched_issues
    ]

    output_data = {
        "issues": results
    }

    OUTPUT_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with OUTPUT_PATH.open(
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            output_data,
            file,
            ensure_ascii=False,
            indent=2,
        )

    fallback_count = sum(
        1
        for result in results
        if result.get("analysis_status")
        == "fallback"
    )

    print(
        f"\n총 {len(results)}개 이슈의 "
        f"비교 분석 결과를 "
        f"{OUTPUT_PATH}에 저장했습니다."
    )

    print(
        f"정상 분석: "
        f"{len(results) - fallback_count}개 / "
        f"fallback 저장: {fallback_count}개"
    )


if __name__ == "__main__":
    main()