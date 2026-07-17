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


def calculate_score(article, query, queries=None):
    """
    기사 점수 계산

    - 제목 일치: 10점
    - 본문 일치: 5점
    - 의미 유사도(similarity_score, 있는 경우): 최대 20점 가중
    - 최신성: 24시간 이내 5점, 72시간 이내 2점
    """
    score = 0
    queries = queries or [query]

    title = (article.get("title") or "").lower()
    content = (article.get("content") or article.get("description") or "").lower()

    if any(q.lower() in title for q in queries):
        score += 10

    if any(q.lower() in content for q in queries):
        score += 5

    similarity_score = article.get("similarity_score")
    if similarity_score:
        score += similarity_score * 20

    published_at = parse_datetime(article.get("published_at"))
    now = datetime.now(timezone.utc)
    hours_diff = (now - published_at).total_seconds() / 3600

    if hours_diff <= 24:
        score += 5
    elif hours_diff <= 72:
        score += 2

    return round(score, 2)


if __name__ == "__main__":
    sample_article = {
        "title": "한국은행 기준금리 동결",
        "content": "한국은행 금융통화위원회가 기준금리를 동결했다.",
        "published_at": "2026-07-17T09:00:00+00:00",
    }

    print("테스트 점수:", calculate_score(sample_article, "금리"))