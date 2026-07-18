from __future__ import annotations

import os
import sys
from pathlib import Path

from flask import Flask, jsonify, request


PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = PROJECT_ROOT / "scripts"

if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from search_engine import search_with_context  # noqa: E402


app = Flask(__name__)


@app.get("/api/debug/vector-store")
def debug_vector_store():
    records_path = PROJECT_ROOT / "data" / "vector_store" / "records.json"
    embeddings_path = PROJECT_ROOT / "data" / "vector_store" / "embeddings.npy"

    return jsonify(
        {
            "project_root": str(PROJECT_ROOT),
            "upstage_api_key_configured": bool(
                os.getenv("UPSTAGE_API_KEY")
            ),
            "records_exists": records_path.exists(),
            "records_size": (
                records_path.stat().st_size
                if records_path.exists()
                else 0
            ),
            "embeddings_exists": embeddings_path.exists(),
            "embeddings_size": (
                embeddings_path.stat().st_size
                if embeddings_path.exists()
                else 0
            ),
        }
    )

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


if __name__ == "__main__":
    app.run(
        host="127.0.0.1",
        port=8000,
        debug=True,
    )

