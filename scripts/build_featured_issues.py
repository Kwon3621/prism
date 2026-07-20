"""
카테고리별 대표 쿼리로 issue_builder의 Event Grouping을 실행해,
홈페이지 핫토픽 섹션(data/issue.json)을 생성하는 배치 스크립트.

개별 기사의 검색 관련도로 먼저 거르는 대신, 사건 단위로 먼저 묶은 뒤
그 묶음을 언론사 수·기사 수·최신성 종합 점수로 평가하는
build_ranked_event_candidates()를 쓴다 (issue_builder.py 참고).

app.js의 renderFeaturedIssue()가 카드를 클릭하면 재검색 없이 곧바로
POST /api/issue로 넘길 수 있어야 하므로, candidate(issue_id/issue_title/
summary/query/expanded_queries/publishers)를 그대로 저장한다.
publishers[].articles[]에는 article_id 등 analyze_issue_batch()가
요구하는 원본 필드가 이미 들어 있다.
"""

from __future__ import annotations

import json
from pathlib import Path

from analysis import create_client
from issue_builder import build_ranked_event_candidates


CATEGORIES = ["정치", "경제", "사회"]
CANDIDATES_PER_CATEGORY = 3
OUTPUT_PATH = Path("data/issue.json")


def build_featured_issues() -> dict:
    client = create_client()

    issues = []
    seen_issue_ids: set[str] = set()

    for category in CATEGORIES:
        try:
            result = build_ranked_event_candidates(
                client,
                category,
                max_candidates=CANDIDATES_PER_CATEGORY,
            )
        except Exception as error:
            print(f"[{category}] 핫토픽 생성 실패: {error}")
            continue

        for candidate in result["candidates"]:
            issue_id = candidate["issue_id"]

            if issue_id in seen_issue_ids:
                continue

            seen_issue_ids.add(issue_id)

            issues.append(
                {
                    **candidate,
                    "category": category,
                    "keywords": candidate.get("expanded_queries", [])[:5],
                }
            )

    # 카테고리 순서가 아니라, 사건 묶음 점수(언론사 수·기사 수·최신성)가
    # 높은 순으로 보여준다.
    issues.sort(
        key=lambda issue: issue.get("group_score", 0),
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
