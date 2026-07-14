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

    solar_by_publisher = {
        article.get("publisher"): article
        for article in solar_articles
        if article.get("publisher")
    }

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

    # 모델이 값을 누락하더라도 기본 식별자는 유지한다.
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

    results = []

    for matched_issue in matched_issues:
        result = analyze_issue(
            client,
            matched_issue,
        )

        results.append(result)

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

    print(
        f"\n총 {len(results)}개 이슈의 "
        f"비교 분석 결과를 "
        f"{OUTPUT_PATH}에 저장했습니다."
    )


if __name__ == "__main__":
    main()