"""
카테고리별로 넓은 검색어("정치"/"경제"/"사회")를 issue_builder의
extract_query_keywords()에 먼저 넣어 그날 실제로 여러 언론사가 다루는
구체적 키워드로 좁힌 뒤, 그 키워드마다 build_candidate_from_keyword()로
비교 카드를 조립해 홈페이지 핫토픽 섹션(data/issue.json)을 생성하는
배치 스크립트.

카테고리명을 그대로 Event Grouping에 넣던 이전 방식
(issue_builder.build_ranked_event_candidates, 현재
scripts/legacy/hot_topic_ranked_candidates.py로 이동)은 관련도 컷 비율을
아무리 조정해도 오배정이 잦아서 폐기했다 — 경위는
issue_builder.extract_query_keywords() 참고.

app.js의 renderFeaturedIssue()가 카드를 클릭하면 재검색 없이 곧바로
POST /api/issue로 넘길 수 있어야 하므로, candidate(issue_id/issue_title/
summary/query/publishers)를 그대로 저장한다. publishers[].articles[]에는
article_id 등 analyze_issue_batch()가 요구하는 원본 필드가 이미 들어 있다.
"""

from __future__ import annotations

import json
from pathlib import Path

from analysis import create_client
from issue_builder import build_candidate_from_keyword, extract_query_keywords


CATEGORIES = ["정치", "경제", "사회"]
CANDIDATES_PER_CATEGORY = 3
OUTPUT_PATH = Path("data/issue.json")


def build_featured_issues() -> dict:
    client = create_client()

    issues = []
    seen_issue_ids: set[str] = set()

    for category in CATEGORIES:
        try:
            result = extract_query_keywords(
                client,
                category,
                max_keywords=CANDIDATES_PER_CATEGORY,
            )
        except Exception as error:
            print(f"[{category}] 핫토픽 키워드 추출 실패: {error}")
            continue

        articles_by_id = result["articles_by_id"]

        for keyword_item in result["keywords"]:
            candidate = build_candidate_from_keyword(
                category,
                keyword_item,
                articles_by_id,
            )

            if candidate is None:
                continue

            issue_id = candidate["issue_id"]

            if issue_id in seen_issue_ids:
                continue

            seen_issue_ids.add(issue_id)

            issues.append(
                {
                    **candidate,
                    "category": category,
                    "keywords": [keyword_item["keyword"]],
                    "publisher_count": keyword_item["publisher_count"],
                    "article_count": keyword_item["article_count"],
                }
            )

    # 카테고리 순서가 아니라, 키워드 비중(언론사 수·기사 수)이 높은
    # 순으로 보여준다.
    issues.sort(
        key=lambda issue: (
            issue.get("publisher_count", 0),
            issue.get("article_count", 0),
        ),
        reverse=True,
    )

    return {"issues": issues}


def save_issues(data: dict) -> None:
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    with OUTPUT_PATH.open("w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)

    print(f"핫토픽 {len(data['issues'])}개 저장 완료: {OUTPUT_PATH}")


def main() -> None:
    data = build_featured_issues()

    if not data["issues"]:
        print("생성된 핫토픽이 없어 기존 data/issue.json을 유지합니다.")
        return

    save_issues(data)


if __name__ == "__main__":
    main()
