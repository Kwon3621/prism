from __future__ import annotations

import sys
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
from analysis import create_client, analyze_issue_batch  # noqa: E402
from compare import analyze_input_data as analyze_comparison_input  # noqa: E402


app = Flask(__name__)



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
        result = analyze_issue_batch(body)

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

