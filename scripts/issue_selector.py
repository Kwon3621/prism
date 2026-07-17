from datetime import datetime, timezone


def parse_datetime(value):
    """
    날짜 문자열을 datetime으로 변환한다.
    변환할 수 없으면 가장 오래된 날짜로 처리한다.
    """
    if not value:
        return datetime.min.replace(tzinfo=timezone.utc)

    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return datetime.min.replace(tzinfo=timezone.utc)


def select_representative_articles(articles, max_per_publisher=1):
    """
    언론사별 대표 기사를 선택한다.

    우선순위:
    1. similarity_score가 높은 기사
    2. published_at이 최신인 기사
    """
    grouped_articles = {}

    for article in articles:
        publisher = article.get("publisher")

        if not publisher:
            continue

        grouped_articles.setdefault(publisher, []).append(article)

    selected_articles = {}

    for publisher, publisher_articles in grouped_articles.items():
        sorted_articles = sorted(
            publisher_articles,
            key=lambda article: (
                article.get("similarity_score", 0),
                parse_datetime(article.get("published_at")),
            ),
            reverse=True,
        )

        selected = []

        if sorted_articles:
            # 가장 점수가 높은 기사 1개는 항상 선택
            selected.append(sorted_articles[0])

            # 2위 기사도 충분히 관련성이 높으면 함께 선택
            if (
                len(sorted_articles) > 1
                and sorted_articles[1].get("similarity_score", 0) >= 0.85
                and max_per_publisher >= 2
            ):
                selected.append(sorted_articles[1])

        selected_articles[publisher] = selected

    return selected_articles

def build_analysis_input(
    *,
    issue_id,
    issue_title,
    query,
    expanded_queries,
    selected_articles,
):
    """
    언론사별 대표 기사 선택 결과를
    analysis.analyze_issue_batch() 입력 구조로 변환한다.
    """
    issue_id = str(
        issue_id or ""
    ).strip()

    issue_title = str(
        issue_title or ""
    ).strip()

    query = str(
        query or ""
    ).strip()

    if not issue_id:
        raise ValueError(
            "issue_id가 비어 있습니다."
        )

    if not issue_title:
        raise ValueError(
            "issue_title이 비어 있습니다."
        )

    if not isinstance(
        selected_articles,
        dict,
    ):
        raise ValueError(
            "selected_articles는 딕셔너리여야 합니다."
        )

    cleaned_expanded_queries = []
    seen_queries = set()

    for expanded_query in (
        expanded_queries or []
    ):
        expanded_query = str(
            expanded_query or ""
        ).strip()

        if not expanded_query:
            continue

        normalized_query = (
            expanded_query.lower()
        )

        if normalized_query in seen_queries:
            continue

        seen_queries.add(
            normalized_query
        )

        cleaned_expanded_queries.append(
            expanded_query
        )

    publishers = []

    for (
        publisher,
        articles,
    ) in selected_articles.items():
        publisher = str(
            publisher or ""
        ).strip()

        if not publisher:
            continue

        if not isinstance(articles, list):
            continue

        valid_articles = [
            article
            for article in articles
            if isinstance(article, dict)
        ]

        if not valid_articles:
            continue

        publisher_ids = {
            str(
                article.get(
                    "publisher_id"
                )
                or ""
            ).strip()
            for article in valid_articles
            if str(
                article.get(
                    "publisher_id"
                )
                or ""
            ).strip()
        }

        if len(publisher_ids) != 1:
            raise ValueError(
                f"{publisher} 대표 기사에서 "
                "publisher_id를 하나로 결정할 수 없습니다: "
                f"{sorted(publisher_ids)}"
            )

        publisher_id = next(
            iter(publisher_ids)
        )

        normalized_articles = []

        for article in valid_articles:
            article_id = str(
                article.get(
                    "article_id"
                )
                or ""
            ).strip()

            title = str(
                article.get(
                    "title"
                )
                or ""
            ).strip()

            if not article_id or not title:
                continue

            normalized_articles.append(
                {
                    "article_id": article_id,
                    "title": title,
                    "description": str(
                        article.get(
                            "description"
                        )
                        or article.get(
                            "content"
                        )
                        or ""
                    ).strip(),
                    "published_at": str(
                        article.get(
                            "published_at"
                        )
                        or article.get(
                            "published"
                        )
                        or ""
                    ).strip(),
                    "link": str(
                        article.get(
                            "link"
                        )
                        or ""
                    ).strip(),
                    "category": str(
                        article.get(
                            "category"
                        )
                        or ""
                    ).strip(),
                }
            )

        if not normalized_articles:
            continue

        publishers.append(
            {
                "publisher_id": (
                    publisher_id
                ),
                "publisher": publisher,
                "articles": (
                    normalized_articles[:2]
                ),
            }
        )

    if len(publishers) < 2:
        raise ValueError(
            "분석 가능한 언론사가 2개 미만입니다."
        )

    return {
        "issue_id": issue_id,
        "issue_title": issue_title,
        "query": query,
        "expanded_queries": (
            cleaned_expanded_queries
        ),
        "publishers": publishers,
    }

def prepare_issue_analysis_input(
    *,
    issue_id,
    issue_title,
    search_context,
    max_per_publisher=2,
):
    """
    search_with_context() 결과를 받아
    analyze_issue_batch() 입력 구조를 생성한다.
    """
    if not isinstance(search_context, dict):
        raise ValueError(
            "search_context는 딕셔너리여야 합니다."
        )

    query = str(
        search_context.get("query") or ""
    ).strip()

    expanded_queries = search_context.get(
        "expanded_queries",
        [],
    )

    search_results = search_context.get(
        "results",
        [],
    )

    if not isinstance(search_results, list):
        raise ValueError(
            "search_context의 results는 배열이어야 합니다."
        )

    selected_articles = (
        select_representative_articles(
            search_results,
            max_per_publisher=max_per_publisher,
        )
    )

    return build_analysis_input(
        issue_id=issue_id,
        issue_title=issue_title,
        query=query,
        expanded_queries=expanded_queries,
        selected_articles=selected_articles,
    )
def score_hot_topic(topic):
    """
    핫토픽 점수 계산 기준
    - 언론사 수 (다양한 언론사가 다뤘는지)
    - 기사 수 (얼마나 많이 다뤄졌는지)
    - 최신성 (가장 최근 기사 기준)

    topic 형태 예시:
    {"topic_id": "t1", "articles": [기사 딕셔너리, ...]}
    """
    articles = topic.get("articles", [])

    publisher_count = len({a.get("publisher") for a in articles if a.get("publisher")})
    article_count = len(articles)

    most_recent = max(
        (parse_datetime(a.get("published_at")) for a in articles),
        default=datetime.min.replace(tzinfo=timezone.utc),
    )

    now = datetime.now(timezone.utc)
    hours_since = (now - most_recent).total_seconds() / 3600
    recency_score = max(0, 24 - hours_since) / 24 * 10  # 24시간 이내일수록 최대 10점

    score = (publisher_count * 5) + (article_count * 1) + recency_score

    return round(score, 2)


def select_hot_topics(topics, top_n=5):
    """
    여러 토픽(이슈) 후보 중 핫토픽 top_n개를 선정한다.
    topics: [{"topic_id":..., "articles":[...]}, ...] 형태의 리스트
    (토픽 묶음 자체는 A팀 임베딩/클러스터링 완료 후 넘어올 예정.
     지금은 이 선정 로직만 미리 완성해둔다.)
    """
    scored_topics = [
        {**topic, "hot_score": score_hot_topic(topic)}
        for topic in topics
    ]

    return sorted(scored_topics, key=lambda t: t["hot_score"], reverse=True)[:top_n]

if __name__ == "__main__":
    sample_articles = [
        {
            "title": "한국은행 기준금리 동결",
            "publisher": "한국경제",
            "similarity_score": 0.91,
            "published_at": "2026-07-17T10:00:00",
        },
        {
            "title": "금리 동결에 시장 반응",
            "publisher": "한국경제",
            "similarity_score": 0.82,
            "published_at": "2026-07-17T15:00:00",
        },
        {
            "title": "기준금리 동결 배경은",
            "publisher": "한겨레",
            "similarity_score": 0.88,
            "published_at": "2026-07-17T12:00:00",
        },
        {
            "title": "금리 동결 이후 증시 영향",
            "publisher": "한국경제",
            "similarity_score": 0.87,
            "published_at": "2026-07-17T13:00:00",
        },
    ]

    result = select_representative_articles(
        sample_articles,
        max_per_publisher=2
    )

    for publisher, articles in result.items():
        print(f"\n{publisher}")

        for article in articles:
            print(
                f"- {article['title']} "
                f"(유사도: {article['similarity_score']})"
            )
    
    print("\n--- 핫토픽 선정 테스트 ---")

    sample_topics = [
        {
            "topic_id": "t1",
            "articles": [
                {"publisher": "한국경제", "published_at": "2026-07-17T09:00:00+00:00"},
                {"publisher": "한겨레", "published_at": "2026-07-17T10:00:00+00:00"},
                {"publisher": "조선일보", "published_at": "2026-07-16T09:00:00+00:00"},
            ],
        },
        {
            "topic_id": "t2",
            "articles": [
                {"publisher": "매일경제", "published_at": "2026-07-15T09:00:00+00:00"},
            ],
        },
    ]

    hot_topics = select_hot_topics(sample_topics, top_n=2)

    for topic in hot_topics:
        print(f"{topic['topic_id']} - 점수: {topic['hot_score']}")
