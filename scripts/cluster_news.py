import json
import re
from collections import defaultdict
from pathlib import Path

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


NEWS_PATH = Path("data/news.json")
OUTPUT_PATH = Path("data/clusters.json")

# 값이 높을수록 더 엄격하게 같은 사건으로 판단한다.
SIMILARITY_THRESHOLD = 0.28


def clean_text(text):
    """
    제목과 RSS 설명의 불필요한 공백 및 특수문자를 정리한다.
    """
    if not text:
        return ""

    text = re.sub(r"\s+", " ", text)
    return text.strip()


def make_article_text(article):
    """
    제목을 RSS 설명보다 더 중요하게 반영하기 위해 제목을 두 번 사용한다.
    """
    title = clean_text(article.get("title", ""))
    description = clean_text(article.get("description", ""))

    return f"{title} {title} {description}"

def group_articles_by_category_and_publisher(news_items):
    """
    기사를 카테고리와 언론사 기준으로 나눈다.

    결과 예시:
    {
        "정치": {
            "조선일보": [...],
            "한겨레": [...]
        },
        "경제": {
            "조선일보": [...],
            "한겨레": [...]
        }
    }
    """
    grouped_articles = defaultdict(
        lambda: defaultdict(list)
    )

    for article in news_items:
        category = article.get("category", "기타")
        publisher = article.get("publisher", "언론사 미상")

        grouped_articles[category][publisher].append(article)

    return grouped_articles

class UnionFind:
    """
    서로 유사한 기사들을 하나의 그룹으로 합치기 위한 자료구조.
    """

    def __init__(self, size):
        self.parent = list(range(size))

    def find(self, index):
        if self.parent[index] != index:
            self.parent[index] = self.find(self.parent[index])

        return self.parent[index]

    def union(self, first, second):
        first_root = self.find(first)
        second_root = self.find(second)

        if first_root != second_root:
            self.parent[second_root] = first_root


def create_topic_title(articles):
    """
    클러스터의 대표 제목은 가장 짧은 기사 제목을 임시로 사용한다.
    이후 Solar 비교 단계에서 더 중립적인 제목으로 다시 생성할 수 있다.
    """
    titles = [
        article.get("title", "").strip()
        for article in articles
        if article.get("title", "").strip()
    ]

    if not titles:
        return "제목 없음"

    return min(titles, key=len)


def cluster_articles(news_items):
    if not news_items:
        return []

    article_texts = [
        make_article_text(article)
        for article in news_items
    ]

    # 한국어 형태소 분석기를 따로 사용하지 않고,
    # 문자 2~5글자 조각을 기준으로 유사도를 계산한다.
    vectorizer = TfidfVectorizer(
        analyzer="char_wb",
        ngram_range=(2, 5),
        min_df=1,
        sublinear_tf=True,
    )

    tfidf_matrix = vectorizer.fit_transform(article_texts)
    similarity_matrix = cosine_similarity(tfidf_matrix)

        # 서로 다른 언론사 기사 쌍의 유사도를 높은 순서대로 확인
    similarity_candidates = []

    for first_index in range(len(news_items)):
        for second_index in range(first_index + 1, len(news_items)):
            first_article = news_items[first_index]
            second_article = news_items[second_index]

            if first_article["publisher"] == second_article["publisher"]:
                continue

            similarity_candidates.append(
                (
                    float(similarity_matrix[first_index][second_index]),
                    first_index,
                    second_index,
                )
            )

    similarity_candidates.sort(reverse=True)

    print("\n유사도가 높은 서로 다른 언론사 기사 쌍 TOP 10")

    for similarity, first_index, second_index in similarity_candidates[:10]:
        print(f"\n유사도: {similarity:.3f}")
        print(
            f"[{news_items[first_index]['publisher']}] "
            f"{news_items[first_index]['title']}"
        )
        print(
            f"[{news_items[second_index]['publisher']}] "
            f"{news_items[second_index]['title']}"
        )

    union_find = UnionFind(len(news_items))

    matched_pairs = []

    for first_index in range(len(news_items)):
        for second_index in range(first_index + 1, len(news_items)):
            first_article = news_items[first_index]
            second_article = news_items[second_index]

            # 같은 언론사끼리는 비교 후보로 묶지 않는다.
            if first_article["publisher"] == second_article["publisher"]:
                continue

            similarity = similarity_matrix[first_index][second_index]

            if similarity >= SIMILARITY_THRESHOLD:
                union_find.union(first_index, second_index)

                matched_pairs.append(
                    {
                        "first_index": first_index + 1,
                        "second_index": second_index + 1,
                        "similarity": round(float(similarity), 3),
                    }
                )

    grouped_indexes = defaultdict(list)

    for index in range(len(news_items)):
        root = union_find.find(index)
        grouped_indexes[root].append(index)

    clusters = []

    for indexes in grouped_indexes.values():
        articles = [news_items[index] for index in indexes]
        publishers = {
            article["publisher"]
            for article in articles
        }

        # 서로 다른 언론사가 포함된 그룹만 남긴다.
        if len(publishers) < 2:
            continue

        cluster_number = len(clusters) + 1

        clusters.append(
            {
                "cluster_id": f"cluster-{cluster_number}",
                "topic_title": create_topic_title(articles),
                "article_indexes": [
                    index + 1
                    for index in indexes
                ],
            }
        )

    return clusters, matched_pairs


def main():
    if not NEWS_PATH.exists():
        raise FileNotFoundError(
            f"{NEWS_PATH} 파일이 없습니다. "
            "먼저 generate_news.py를 실행하세요."
        )

    with NEWS_PATH.open("r", encoding="utf-8") as file:
        news_items = json.load(file)

    grouped_articles = group_articles_by_category_and_publisher(
        news_items
    )

    print("\n카테고리·언론사별 기사 수")

    for category, publishers in grouped_articles.items():
        for publisher, articles in publishers.items():
            print(
                f"{category} - {publisher}: "
                f"{len(articles)}개"
            )

    clusters, matched_pairs = cluster_articles(news_items)

    result = {
        "similarity_threshold": SIMILARITY_THRESHOLD,
        "clusters": clusters,
        "matched_pairs": matched_pairs,
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    with OUTPUT_PATH.open("w", encoding="utf-8") as file:
        json.dump(
            result,
            file,
            ensure_ascii=False,
            indent=2,
        )

    print(f"전체 기사 수: {len(news_items)}개")
    print(f"유사 기사 쌍: {len(matched_pairs)}개")
    print(f"비교 가능한 클러스터: {len(clusters)}개")
    print(f"결과 저장 위치: {OUTPUT_PATH}")

    for cluster in clusters:
        print(
            f"- {cluster['cluster_id']}: "
            f"{cluster['topic_title']} "
            f"{cluster['article_indexes']}"
        )


if __name__ == "__main__":
    main()