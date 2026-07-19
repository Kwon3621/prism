from __future__ import annotations

import sys
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory


PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = PROJECT_ROOT / "scripts"

if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from search_engine import search_with_context  # noqa: E402
from issue_builder import build_issue_candidates  # noqa: E402
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
        result = build_issue_candidates(client, query)

        return jsonify(
            {
                "success": True,
                "query": query,
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

