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

카드마다 언론사별 분석·그룹화·조합별 비교까지 이 배치에서 미리 계산해
data/issue_details.json에 저장한다(build_precomputed_comparisons 참고).
방문자가 핫토픽 카드로 들어오면 app.js가 이 정적 데이터를 먼저 찾아보고, 있으면
/api/issue·/api/compare를 아예 호출하지 않고 그대로 렌더링한다 — 뉴스가
다음 배치로 갱신되기 전까지는 몇 명이 같은 카드를 보든 Solar를 다시
부르지 않는다는 뜻이다. data/issue.json 자체(홈 화면 카드 목록에 쓰임,
모든 방문자가 매번 받는 파일)에는 이 무거운 데이터를 넣지 않고 별도
파일로 분리했다 — 안 그러면 클릭 여부와 무관하게 모든 방문자의 홈 화면
로딩이 무거워진다.
"""

from __future__ import annotations

import itertools
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from analysis import analyze_issue_batch, create_client
from compare import compare_publishers
from issue_builder import build_candidate_from_keyword, extract_query_keywords


CATEGORIES = ["정치", "경제", "사회"]
CANDIDATES_PER_CATEGORY = 3
OUTPUT_PATH = Path("data/issue.json")
DETAILS_OUTPUT_PATH = Path("data/issue_details.json")

# compare.py가 한 번에 받을 수 있는 언론사 조합 크기(2~4개)와 동일하게 맞춘다.
MIN_COMPARISON_SIZE = 2
MAX_COMPARISON_SIZE = 4

# 언론사 6곳짜리 이슈는 조합이 50개까지 나온다. 순서대로 부르면 이
# 배치 하나가 지나치게 오래 걸려서, 다른 단계(언론사별 분석)와 같은
# 방식으로 동시에 호출하되 Upstage 쪽에 한 번에 너무 몰리지 않도록
# 동시 실행 수는 제한한다.
MAX_COMPARISON_WORKERS = 8


def build_precomputed_comparisons(
    client,
    publisher_analyses: list[dict],
) -> dict[str, dict]:
    """
    가능한 모든 2~4개 언론사 조합의 비교 결과와, "이슈 전체 언론사"
    조합(공통 내용 요약 카드용, app.js:renderOverallCommonSummary 참고)의
    비교 결과를 미리 계산한다.

    실시간 요청에서는 방문자마다 다른 조합을 고를 수 있어 조합 전체를
    미리 계산해두면 동시 접속이 몰릴 때 Solar 호출이 조합 수만큼
    폭발적으로 늘어난다(최대 언론사 6곳이면 50개 조합). 하지만 여기는
    트래픽 압박이 없는 배치 시점(6시간마다 한 번)이라, 조합을 전부
    미리 계산해도 부담이 없다 — 방문자는 어떤 조합을 고르든 이미
    계산된 결과를 정적으로 받기만 하면 된다.

    상세 대조표는 UI상 2~4개까지만 선택 가능하지만(app.js:
    initPublisherSelector), 공통 내용 요약은 그 4개 제한과 무관하게 이슈에
    포함된 언론사 전체를 compare.py에 보낸다. 언론사가 5~6곳이면 "전체"
    조합이 2~4개 범위 밖이라 별도로 추가해준다.
    """
    max_combo_size = min(MAX_COMPARISON_SIZE, len(publisher_analyses))
    sizes = set(range(MIN_COMPARISON_SIZE, max_combo_size + 1))

    if len(publisher_analyses) > MAX_COMPARISON_SIZE:
        sizes.add(len(publisher_analyses))

    combos_by_key = {
        ",".join(sorted(item["publisher_id"] for item in combo)): list(combo)
        for size in sizes
        for combo in itertools.combinations(publisher_analyses, size)
    }

    comparisons: dict[str, dict] = {}

    with ThreadPoolExecutor(
        max_workers=min(len(combos_by_key), MAX_COMPARISON_WORKERS)
    ) as executor:
        future_to_key = {
            executor.submit(
                compare_publishers,
                client=client,
                publisher_analyses=combo,
            ): combo_key
            for combo_key, combo in combos_by_key.items()
        }

        for future in as_completed(future_to_key):
            combo_key = future_to_key[future]

            try:
                comparisons[combo_key] = future.result()
            except Exception as error:
                print(f"    [조합 비교 실패] {combo_key}: {error}")

    return comparisons


def build_featured_issues() -> dict:
    client = create_client()

    issues = []
    issue_details: dict[str, dict] = {}
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

            # 언론사별 분석·그룹화·조합별 비교를 여기서 미리 계산해둔다.
            # 실패해도(예: Solar 일시 오류) 핫토픽 카드 자체는 이미
            # 목록에 들어갔으니, 이 이슈만 방문 시 실시간 계산으로
            # 자연스럽게 대체된다(app.js:resolvePrecomputedIssueData).
            try:
                print(f"  [사전 계산] {candidate['issue_title']}")

                analysis_result = analyze_issue_batch(
                    candidate,
                    use_cache=True,
                )

                publisher_analyses = analysis_result[
                    "publisher_analyses"
                ]

                if len(publisher_analyses) < 2:
                    continue

                issue_details[issue_id] = {
                    "publisher_analyses": publisher_analyses,
                    "publisher_grouping": analysis_result[
                        "publisher_grouping"
                    ],
                    "comparisons": build_precomputed_comparisons(
                        client,
                        publisher_analyses,
                    ),
                }

            except Exception as error:
                print(
                    f"  [사전 계산 실패] {candidate['issue_title']}: "
                    f"{error} (방문 시 실시간 계산으로 대체)"
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

    return {"issues": issues, "issue_details": issue_details}


def save_issues(data: dict) -> None:
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    with OUTPUT_PATH.open("w", encoding="utf-8") as file:
        json.dump(
            {"issues": data["issues"]},
            file,
            ensure_ascii=False,
            indent=2,
        )

    print(f"핫토픽 {len(data['issues'])}개 저장 완료: {OUTPUT_PATH}")


def save_issue_details(data: dict) -> None:
    """
    언론사별 분석·그룹화·조합별 비교를 담은 무거운 데이터는 홈 화면이
    매번 받는 data/issue.json과 분리된 파일로 저장한다. 안 그러면 카드를
    클릭하지 않는 방문자까지 이 무거운 데이터를 매번 내려받게 된다.
    """
    DETAILS_OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    with DETAILS_OUTPUT_PATH.open("w", encoding="utf-8") as file:
        json.dump(
            data["issue_details"],
            file,
            ensure_ascii=False,
            indent=2,
        )

    print(
        f"핫토픽 사전 계산 데이터 {len(data['issue_details'])}개 저장 "
        f"완료: {DETAILS_OUTPUT_PATH}"
    )


def main() -> None:
    data = build_featured_issues()

    if not data["issues"]:
        print("생성된 핫토픽이 없어 기존 data/issue.json을 유지합니다.")
        return

    save_issues(data)
    save_issue_details(data)


if __name__ == "__main__":
    main()
