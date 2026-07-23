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

from analysis import analyze_issue_batch, create_client, group_publishers
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

# compare_publishers()는 내부적으로 이미 3회 재시도하지만, 그래도 실패하면
# 그 조합은 정적 파일에서 빠지고 방문 시 실시간 계산으로 샌다. 배치는
# 트래픽 압박이 없는 시점이라 통째로 몇 번 더 재시도해서 최대한 모든
# 조합을 정적 데이터로 남긴다.
MAX_COMBO_RETRY_ATTEMPTS = 3

# Publisher Grouping이 언론사를 누락시키면(Solar 응답 누락) analysis.py가
# "개별 분류 (그룹화 보류)"로 복구하는데, 실시간 요청은 응답성을 위해
# 그 결과를 그대로 쓴다. 배치는 여유가 있으니 그룹화 보류가 없는 깨끗한
# 결과가 나올 때까지 몇 번 더 시도해본다.
MAX_GROUPING_RETRIES = 5

# compare_publishers()는 overall_difference="판단 어려움"이면 실시간
# 요청에서도 1회는 자체적으로 재시도하지만(compare.py 참고), 그래도
# 여전히 판단 어려움이면 실시간에서는 API 사용량·응답 지연 때문에 더
# 반복하지 않는다. "이슈 전체" 조합(공통 내용 요약 카드에 쓰임)만큼은
# 그룹화 보류와 같은 수준으로, 배치 시점에 한해 몇 번 더 시도해서 더
# 결정적인 결과가 정적 데이터로 남게 한다. 조합이 최대 50개까지 나올 수
# 있는 상세 대조표 조합에는 적용하지 않는다 — 비용 대비 이득이 낮다.
MAX_SUMMARY_QUALITY_RETRIES = 5


def _regenerate_comparison_until_decisive(
    client,
    combo: list[dict],
    max_attempts: int = MAX_SUMMARY_QUALITY_RETRIES,
) -> dict:
    """
    "이슈 전체" 조합의 비교 결과가 판단 어려움이면, 더 결정적인 결과가
    나오거나 시도 횟수를 다 쓸 때까지 완전히 새로 재생성한다
    (build_complete_grouping과 같은 방식). 매번 use_cache=False로 캐시를
    건너뛰어야 Solar를 다시 불러 다른 결과를 얻을 여지가 생긴다.
    """
    combo_key = ",".join(
        sorted(item["publisher_id"] for item in combo)
    )

    best_result: dict | None = None

    for attempt in range(1, max_attempts + 1):
        try:
            result = compare_publishers(
                client=client,
                publisher_analyses=combo,
                use_cache=False,
            )
        except Exception as error:
            print(
                f"    [공통 요약 재시도] {combo_key} "
                f"{attempt}/{max_attempts} 호출 실패: {error}"
            )
            continue

        if result.get("overall_difference") != "판단 어려움":
            return result

        if best_result is None:
            best_result = result

        print(
            f"    [공통 요약 재시도] {combo_key} "
            f"{attempt}/{max_attempts}: 여전히 판단 어려움, 다시 시도"
        )

    print(
        f"    [공통 요약] {combo_key}: {max_attempts}회 시도해도 "
        "판단 어려움이 남아 마지막 결과를 사용합니다."
    )

    if best_result is not None:
        return best_result

    raise RuntimeError(
        f"{combo_key} 조합의 공통 요약을 "
        f"{max_attempts}회 모두 생성하지 못했습니다."
    )


def _compare_combo_with_retries(
    client,
    combo: list[dict],
) -> dict:
    """
    compare_publishers()가 내부 3회 재시도까지 다 실패해도, 배치
    시점이라 부담 없이 통째로 몇 번 더 시도해서 최대한 정적 데이터로
    남긴다. 마지막 시도까지 실패하면 그 에러를 그대로 올려서 호출부가
    이 조합만 결과에서 빼도록 한다.
    """
    last_error: Exception | None = None

    for attempt in range(1, MAX_COMBO_RETRY_ATTEMPTS + 1):
        try:
            return compare_publishers(
                client=client,
                publisher_analyses=combo,
            )
        except Exception as error:
            last_error = error

            combo_key = ",".join(
                sorted(item["publisher_id"] for item in combo)
            )

            print(
                f"    [조합 비교 재시도] {combo_key} "
                f"{attempt}/{MAX_COMBO_RETRY_ATTEMPTS}: {error}"
            )

    raise last_error


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

    # "이슈 전체" 조합(공통 내용 요약에 쓰이는 조합)만 판단 어려움 재시도를
    # 추가로 적용한다. 나머지 상세 대조표 조합(최대 50개)까지 다 적용하면
    # 비용 대비 이득이 낮다.
    full_combo_key = ",".join(
        sorted(item["publisher_id"] for item in publisher_analyses)
    )

    comparisons: dict[str, dict] = {}

    with ThreadPoolExecutor(
        max_workers=min(len(combos_by_key), MAX_COMPARISON_WORKERS)
    ) as executor:
        future_to_key = {}

        for combo_key, combo in combos_by_key.items():
            worker = (
                _regenerate_comparison_until_decisive
                if combo_key == full_combo_key
                else _compare_combo_with_retries
            )

            future_to_key[
                executor.submit(worker, client, combo)
            ] = combo_key

        for future in as_completed(future_to_key):
            combo_key = future_to_key[future]

            try:
                comparisons[combo_key] = future.result()
            except Exception as error:
                print(f"    [조합 비교 실패] {combo_key}: {error}")

    return comparisons


def _count_pending_groups(grouping_result: dict) -> int:
    """
    Publisher Grouping이 언론사를 누락시켜 코드가 복구한 "그룹화 보류"
    항목이 몇 개나 섞여 있는지 센다. 복구된 그룹은 analysis.py:
    validate_grouping_result에서 group_id를 "group-ungrouped-"로 붙인다.
    """
    return sum(
        1
        for group in grouping_result.get("groups", [])
        if str(group.get("group_id", "")).startswith("group-ungrouped-")
    )


def build_complete_grouping(
    client,
    publisher_analyses: list[dict],
) -> dict:
    """
    그룹화 보류 없는 Publisher Grouping 결과가 나올 때까지 재시도한다.

    실시간 요청은 응답성을 위해 Solar가 언론사를 누락시키면 그 자리를
    "개별 분류(그룹화 보류)"로 즉시 복구하고 넘어가지만(analysis.py:
    group_publishers), 배치는 트래픽 압박이 없으니 깨끗한 결과가 나올
    때까지 통째로 다시 시도해볼 여유가 있다. 매번 완전히 새로 Solar를
    부르므로(캐시 없음) 시도할 때마다 다른 결과가 나올 수 있다.
    끝까지 깨끗한 결과가 안 나오면, 시도한 것들 중 그룹화 보류가 가장
    적었던 결과를 쓴다.
    """
    best_result = None
    best_pending_count = None

    for attempt in range(1, MAX_GROUPING_RETRIES + 1):
        try:
            result = group_publishers(
                client=client,
                publisher_analyses=publisher_analyses,
            )
        except Exception as error:
            print(
                f"    [그룹화 재시도] {attempt}/{MAX_GROUPING_RETRIES} "
                f"호출 실패: {error}"
            )
            continue

        pending_count = _count_pending_groups(result)

        if pending_count == 0:
            return result

        if best_pending_count is None or pending_count < best_pending_count:
            best_result = result
            best_pending_count = pending_count

        print(
            f"    [그룹화 재시도] {attempt}/{MAX_GROUPING_RETRIES}: "
            f"그룹화 보류 {pending_count}건 발생, 다시 시도"
        )

    print(
        f"    [그룹화] {MAX_GROUPING_RETRIES}회 시도해도 그룹화 보류가 "
        f"남아 있어 그중 가장 적은(그룹화 보류 {best_pending_count}건) "
        "결과를 사용합니다."
    )

    return best_result


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

                publisher_grouping = analysis_result[
                    "publisher_grouping"
                ]

                # analyze_issue_batch가 내부적으로 이미 한 번 그룹화를
                # 했는데, 언론사가 누락돼 "그룹화 보류"로 복구된 상태라면
                # 정적 데이터에 그대로 남기지 않고 깨끗한 결과가 나올
                # 때까지 몇 번 더 시도해본다.
                if _count_pending_groups(publisher_grouping) > 0:
                    print(
                        "    [그룹화] 그룹화 보류 발생, 재시도: "
                        f"{candidate['issue_title']}"
                    )

                    retried_grouping = build_complete_grouping(
                        client,
                        publisher_analyses,
                    )

                    if retried_grouping is not None:
                        publisher_grouping = retried_grouping

                issue_details[issue_id] = {
                    "publisher_analyses": publisher_analyses,
                    "publisher_grouping": publisher_grouping,
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
