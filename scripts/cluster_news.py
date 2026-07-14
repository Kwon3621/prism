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
    """
    같은 카테고리·같은 언론사 안에서만 기사를 비교해
    언론사별 이슈 클러스터를 만든다.
    """
    if not news_items:
        return [], []

    grouped_articles = group_articles_by_category_and_publisher(
        news_items
    )

    # 원본 news.json에서 각 기사의 위치를 찾기 위한 값
    article_index_by_link = {
        article.get("link"): index
        for index, article in enumerate(news_items)
    }

    clusters = []
    matched_pairs = []

    for category, publishers in grouped_articles.items():
        for publisher, publisher_articles in publishers.items():
            if not publisher_articles:
                continue

            print(
                f"\n{category} - {publisher} "
                f"내부 클러스터링 중..."
            )

            article_texts = [
                make_article_text(article)
                for article in publisher_articles
            ]

            vectorizer = TfidfVectorizer(
                analyzer="char_wb",
                ngram_range=(2, 5),
                min_df=1,
                sublinear_tf=True,
            )

            tfidf_matrix = vectorizer.fit_transform(
                article_texts
            )

            similarity_matrix = cosine_similarity(
                tfidf_matrix
            )

            union_find = UnionFind(
                len(publisher_articles)
            )

            similarity_candidates = []

            for first_index in range(
                len(publisher_articles)
            ):
                for second_index in range(
                    first_index + 1,
                    len(publisher_articles),
                ):
                    similarity = float(
                        similarity_matrix[
                            first_index
                        ][second_index]
                    )

                    similarity_candidates.append(
                        (
                            similarity,
                            first_index,
                            second_index,
                        )
                    )

                    if similarity >= SIMILARITY_THRESHOLD:
                        union_find.union(
                            first_index,
                            second_index,
                        )

                        first_article = (
                            publisher_articles[first_index]
                        )
                        second_article = (
                            publisher_articles[second_index]
                        )

                        matched_pairs.append(
                            {
                                "category": category,
                                "publisher": publisher,
                                "first_index": (
                                    article_index_by_link.get(
                                        first_article.get("link")
                                    )
                                    + 1
                                ),
                                "second_index": (
                                    article_index_by_link.get(
                                        second_article.get("link")
                                    )
                                    + 1
                                ),
                                "similarity": round(
                                    similarity,
                                    3,
                                ),
                            }
                        )

            similarity_candidates.sort(
                reverse=True
            )

            print("유사도가 높은 내부 기사 쌍 TOP 5")

            for (
                similarity,
                first_index,
                second_index,
            ) in similarity_candidates[:5]:
                print(f"\n유사도: {similarity:.3f}")
                print(
                    publisher_articles[
                        first_index
                    ]["title"]
                )
                print(
                    publisher_articles[
                        second_index
                    ]["title"]
                )

            grouped_indexes = defaultdict(list)

            for index in range(
                len(publisher_articles)
            ):
                root = union_find.find(index)
                grouped_indexes[root].append(index)

            for local_indexes in grouped_indexes.values():
                articles = [
                    publisher_articles[index]
                    for index in local_indexes
                ]

                original_indexes = [
                    article_index_by_link[
                        article.get("link")
                    ]
                    + 1
                    for article in articles
                ]

                cluster_number = len(clusters) + 1

                clusters.append(
                    {
                        "cluster_id": (
                            f"cluster-{cluster_number}"
                        ),
                        "category": category,
                        "publisher": publisher,
                        "topic_title": create_topic_title(
                            articles
                        ),
                        "article_count": len(articles),
                        "article_indexes": original_indexes,
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
    print(f"언론사 내부 유사 기사 쌍: {len(matched_pairs)}개")
    print(f"언론사 내부 클러스터: {len(clusters)}개")
    print(f"결과 저장 위치: {OUTPUT_PATH}")

    for cluster in clusters:
        print(
            f"- {cluster['cluster_id']}: "
            f"{cluster['topic_title']} "
            f"{cluster['article_indexes']}"
        )


if __name__ == "__main__":
    main()