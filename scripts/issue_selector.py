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
