from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory


PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = PROJECT_ROOT / "scripts"

if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from search_engine import search_with_context  # noqa: E402
from issue_builder import (  # noqa: E402
    build_candidate_from_keyword,
    build_issue_candidates,
    extract_query_keywords,
)
from analysis import (  # noqa: E402
    analyze_publishers_only,
    create_client,
    group_publishers,
)
from compare import analyze_input_data as analyze_comparison_input  # noqa: E402
from cache import (  # noqa: E402
    get_issue_result,
    get_issue_snapshot,
    save_issue_result,
    save_issue_snapshot,
)


app = Flask(__name__)


def _build_default_comparison_combos(
    publisher_analyses: list[dict],
) -> dict[str, list[dict]]:
    """
    실시간 요청에서 프론트가 곧바로 필요로 하는 조합만 골라낸다.

    - "전체": 이슈 전체 언론사 기준 공통 내용 요약
      (app.js:renderOverallCommonSummary)
    - "앞 4개": 상세 대조표 기본 선택값 (app.js:initPublisherSelector)

    언론사가 4곳 이하면 두 조합이 같아져서 dict 키가 자동으로 합쳐지므로
    중복 호출되지 않는다.
    """
    combos_by_key: dict[str, list[dict]] = {}

    for combo in (
        publisher_analyses,
        publisher_analyses[:4],
    ):
        if len(combo) < 2:
            continue

        combo_key = ",".join(
            sorted(item["publisher_id"] for item in combo)
        )

        combos_by_key[combo_key] = combo

    return combos_by_key


def analyze_issue_with_default_comparisons(body: dict) -> dict:
    """
    언론사별 분석이 끝나는 즉시, Publisher Grouping과 프론트가 바로
    필요로 하는 기본 비교 조합(전체/앞 4개)을 동시에 실행한다.

    이 둘은 서로의 결과를 필요로 하지 않고 둘 다 언론사별 분석 결과만
    있으면 되는데, 예전에는 그룹화가 끝나야 이 응답이 돌아가고, 그 다음
    프론트가 /api/compare를 새로 호출해서 사실상 순차 실행되고 있었다.
    여기서 미리 계산해 default_comparisons로 함께 내려주면, 프론트는
    추가 API 호출 없이 그 자리에서 캐시를 채우고 바로 렌더링할 수 있다
    (app.js:resolvePrecomputedIssueData가 핫토픽 정적 데이터에 쓰는 것과
    같은 방식).
    """
    cached_result = get_issue_result(body)

    if cached_result is not None:
        app.logger.info(
            "Issue analysis result cache hit: issue_id=%s",
            body.get("issue_id"),
        )

        return {
            **cached_result,
            "issue_result_cache_hit": True,
        }

    app.logger.info(
        "Issue analysis result cache miss: issue_id=%s",
        body.get("issue_id"),
    )

    analysis_result = analyze_publishers_only(
        body,
        use_cache=True,
    )

    publisher_analyses = analysis_result["publisher_analyses"]
    combos_by_key = _build_default_comparison_combos(publisher_analyses)

    grouping_result = None
    default_comparisons: dict[str, dict] = {}

    with ThreadPoolExecutor(
        max_workers=len(combos_by_key) + 1,
    ) as executor:
        future_to_task = {
            executor.submit(
                group_publishers,
                client=create_client(),
                publisher_analyses=publisher_analyses,
            ): "__grouping__",
        }

        for combo_key, combo in combos_by_key.items():
            future_to_task[
                executor.submit(
                    analyze_comparison_input,
                    {"publisher_analyses": combo},
                )
            ] = combo_key

        for future in as_completed(future_to_task):
            task_key = future_to_task[future]

            if task_key == "__grouping__":
                # 그룹화 실패는 기존 analyze_issue_batch와 동일하게
                # 그대로 전파해서 /api/issue 전체를 실패 처리한다.
                grouping_result = future.result()
                continue

            try:
                default_comparisons[task_key] = future.result()
            except Exception as error:
                # 기본 비교 조합 계산 실패는 치명적이지 않다 — 그
                # 조합만 응답에서 빠지고, 프론트가 필요할 때 실시간
                # /api/compare로 자연스럽게 대체한다.
                app.logger.warning(
                    "기본 비교 조합 계산 실패(%s): %s",
                    task_key,
                    error,
                )

    result = {
        **analysis_result,
        "publisher_grouping": grouping_result,
        "default_comparisons": default_comparisons,
        "processed_at": datetime.now(timezone.utc).isoformat(),
    }

    save_issue_result(
        input_data=body,
        result=result,
    )

    return {
        **result,
        "issue_result_cache_hit": False,
    }



@app.get("/api/health")
def health_api():
    return jsonify(
        {
            "success": True,
            "service": "prism-search-api",
        }
    )


@app.get("/api/search")
def search_api():
    query = str(request.args.get("q") or "").strip()

    if not query:
        return jsonify(
            {
                "success": False,
                "error": "검색어가 비어 있습니다.",
            }
        ), 400

    try:
        search_context = search_with_context(
            query,
            n_results_per_query=20,
        )

        results = search_context.get("results", [])[:30]

        return jsonify(
            {
                "success": True,
                "query": search_context.get("query", query),
                "expanded_queries": search_context.get(
                    "expanded_queries",
                    [],
                ),
                "results": results,
                "result_count": len(results),
            }
        )

    except Exception as error:
        app.logger.exception("검색 API 실행 실패")

        return jsonify(
            {
                "success": False,
                "error": str(error),
            }
        ), 500


@app.get("/api/issue-candidates")
def issue_candidates_api():
    """
    검색어가 "정치"/"경제"/"정청래"처럼 넓거나 인물명 위주라 여러
    사건이 섞여 나올 수 있는 경우, 먼저 extract_query_keywords()로
    구체적 키워드를 뽑고 키워드별 비교 카드를 전부 만들어서 한 번에
    반환한다. 키워드가 2개 이상이면 mode="keywords"로 표시해 프론트가
    "구체화된 키워드를 선택해주세요" 화면을 보여주게 하고, 1개 이하로
    좁혀지면(이미 구체적인 검색어라는 뜻) mode="candidates"로 바로
    카드를 보여준다. 키워드 클릭은 새 요청 없이, 이미 받은 candidates
    배열에서 골라 보여주면 된다.

    키워드 추출 자체가 실패하거나 결과가 하나도 없으면(예: 아주
    희귀한 검색어) build_issue_candidates()로 바로 폴백한다.
    """
    query = str(request.args.get("q") or "").strip()

    if not query:
        return jsonify(
            {
                "success": False,
                "error": "검색어가 비어 있습니다.",
            }
        ), 400

    try:
        client = create_client()

        try:
            keyword_result = extract_query_keywords(client, query)
            articles_by_id = keyword_result["articles_by_id"]

            candidates = [
                candidate
                for candidate in (
                    build_candidate_from_keyword(
                        query,
                        keyword_item,
                        articles_by_id,
                    )
                    for keyword_item in keyword_result["keywords"]
                )
                if candidate is not None
            ]

            if candidates:
                mode = "keywords" if len(candidates) > 1 else "candidates"

                return jsonify(
                    {
                        "success": True,
                        "query": query,
                        "mode": mode,
                        "candidates": candidates,
                    }
                )

        except Exception as error:
            app.logger.info(
                "키워드 추출로 결과를 못 만들어 직접 검색으로 대체: %s",
                error,
            )

        result = build_issue_candidates(client, query)

        return jsonify(
            {
                "success": True,
                "query": query,
                "mode": "candidates",
                **result,
            }
        )

    except ValueError as error:
        return jsonify(
            {
                "success": False,
                "error": str(error),
            }
        ), 400

    except Exception as error:
        app.logger.exception("이슈 후보(Event Grouping) API 실행 실패")

        return jsonify(
            {
                "success": False,
                "error": str(error),
            }
        ), 500


@app.post("/api/issue")
def issue_api():
    body = request.get_json(silent=True) or {}

    try:
        result = analyze_issue_with_default_comparisons(body)

        return jsonify(
            {
                "success": True,
                **result,
            }
        )

    except ValueError as error:
        return jsonify(
            {
                "success": False,
                "error": str(error),
            }
        ), 400

    except Exception as error:
        app.logger.exception("이슈 분석 API 실행 실패")

        return jsonify(
            {
                "success": False,
                "error": str(error),
            }
        ), 500


@app.post("/api/compare")
def compare_api():
    body = request.get_json(silent=True) or {}
    publisher_analyses = body.get("publisher_analyses", [])

    try:
        result = analyze_comparison_input(
            {
                "publisher_analyses": publisher_analyses,
            }
        )

        return jsonify(
            {
                "success": True,
                **result,
            }
        )

    except ValueError as error:
        return jsonify(
            {
                "success": False,
                "error": str(error),
            }
        ), 400

    except Exception as error:
        app.logger.exception("언론사 비교 API 실행 실패")

        return jsonify(
            {
                "success": False,
                "error": str(error),
            }
        ), 500


def _normalize_issue_snapshot(body: dict) -> dict:
    """
    /api/issue-snapshot 저장 요청 바디를 검증하고 정리한다.

    공유 버튼이 보내는 currentIssue에는 화면 표시용 필드(title/summary/
    mediaNames 등)도 섞여 있지만, 복원에 실제로 필요한 건 이 5개뿐이다.
    """
    issue_id = str(body.get("issue_id") or "").strip()
    issue_title = str(body.get("issue_title") or "").strip()
    query = str(body.get("query") or "").strip()
    publisher_analyses = body.get("publisher_analyses")
    publisher_grouping = body.get("publisher_grouping")

    if not issue_id:
        raise ValueError("issue_id가 없습니다.")

    if (
        not isinstance(publisher_analyses, list)
        or len(publisher_analyses) < 2
    ):
        raise ValueError(
            "publisher_analyses는 언론사 2곳 이상을 담은 배열이어야 합니다."
        )

    if not isinstance(publisher_grouping, dict):
        publisher_grouping = {"groups": []}

    return {
        "issue_id": issue_id,
        "issue_title": issue_title,
        "query": query,
        "publisher_analyses": publisher_analyses,
        "publisher_grouping": publisher_grouping,
    }


@app.post("/api/issue-snapshot")
def save_issue_snapshot_api():
    """
    "공유" 버튼을 누른 시점의 분석 스냅샷을 저장한다.

    sessionStorage 핸드오프가 안 통하는 상황(다른 브라우저·기기로 공유
    링크를 열었을 때)에 대비해, 서버에 issue_id 기준으로 스냅샷을 남겨둔다.
    """
    body = request.get_json(silent=True) or {}

    try:
        snapshot = _normalize_issue_snapshot(body)
        save_issue_snapshot(snapshot["issue_id"], snapshot)

        return jsonify({"success": True})

    except ValueError as error:
        return jsonify(
            {
                "success": False,
                "error": str(error),
            }
        ), 400

    except Exception as error:
        app.logger.exception("이슈 스냅샷 저장 API 실행 실패")

        return jsonify(
            {
                "success": False,
                "error": str(error),
            }
        ), 500


@app.get("/api/issue-snapshot/<issue_id>")
def get_issue_snapshot_api(issue_id):
    """
    공유 링크를 통해 들어왔을 때, sessionStorage 핸드오프 대신 조회할
    서버 스냅샷. 없으면(TTL 만료 등) 404를 반환해 프론트가 기존
    재검색 폴백으로 자연스럽게 넘어가게 한다.
    """
    issue_id = str(issue_id or "").strip()

    if not issue_id:
        return jsonify(
            {
                "success": False,
                "error": "issue_id가 없습니다.",
            }
        ), 400

    try:
        snapshot = get_issue_snapshot(issue_id)

        if not snapshot:
            return jsonify(
                {
                    "success": False,
                    "error": "저장된 스냅샷이 없습니다.",
                }
            ), 404

        return jsonify(
            {
                "success": True,
                **snapshot,
            }
        )

    except Exception as error:
        app.logger.exception("이슈 스냅샷 조회 API 실행 실패")

        return jsonify(
            {
                "success": False,
                "error": str(error),
            }
        ), 500


# 로컬 개발 전용 정적 파일 서빙.
# 배포 환경(Vercel)에서는 vercel.json의 rewrite가 /api/* 외의 요청을
# 이 Flask 앱까지 넘기지 않고 정적 호스팅이 직접 처리하므로, 아래 라우트는
# `python api/index.py`로 로컬에서 띄웠을 때만 의미가 있다.
# .env, scripts/*.py 등 노출되면 안 되는 파일을 막기 위해
# 최상위 html/js/css 파일과 data/*.json만 화이트리스트로 서빙한다.
STATIC_EXTENSIONS = {".html", ".js", ".css"}
DATA_EXTENSIONS = {".json"}


@app.get("/")
def serve_index():
    return send_from_directory(PROJECT_ROOT, "index.html")


@app.get("/<path:filename>")
def serve_static_file(filename):
    path = Path(filename)

    if (
        path.suffix in STATIC_EXTENSIONS
        and len(path.parts) == 1
    ):
        return send_from_directory(PROJECT_ROOT, filename)

    if (
        path.suffix in DATA_EXTENSIONS
        and len(path.parts) == 2
        and path.parts[0] == "data"
    ):
        return send_from_directory(
            PROJECT_ROOT / "data",
            path.parts[1],
        )

    return jsonify(
        {
            "success": False,
            "error": "Not Found",
        }
    ), 404


if __name__ == "__main__":
    app.run(
        host="127.0.0.1",
        port=8000,
        debug=True,
    )

