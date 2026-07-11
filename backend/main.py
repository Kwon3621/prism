from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from rss_service import get_sbs_articles


app = FastAPI(title="Prism News API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5500",
        "http://localhost:5500",
        "https://kwon3621.github.io",
    ],
    allow_credentials=True,
    allow_methods=["GET"],
    allow_headers=["*"],
)


@app.get("/")
def root() -> dict[str, str]:
    return {"message": "Prism backend is running"}


@app.get("/api/news")
def search_news(
    query: str = Query(default="", max_length=100),
) -> dict:
    try:
        articles = get_sbs_articles(query)

        return {
            "query": query,
            "count": len(articles),
            "articles": articles,
        }

    except RuntimeError as error:
        raise HTTPException(
            status_code=502,
            detail=str(error),
        ) from error