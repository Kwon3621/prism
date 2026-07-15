import json
import re
from collections import defaultdict
from pathlib import Path

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


NEWS_PATH = Path("data/news.json")
CLUSTERS_PATH = Path("data/clusters.json")
OUTPUT_PATH = Path("data/matched_clusters.json")

# 값이 높을수록 서로 다른 언론사의 클러스터를
# 더 엄격하게 같은 이슈로 판단한다.
CLUSTER_SIMILARITY_THRESHOLD = 0.22


def clean_text(text):
    """
    비교에 사용할 텍스트의 공백을 정리한다.
    """
    if not text:
        return ""

    text = re.sub(r"\s+", " ", str(text))

    return text.strip()


class UnionFind:
    """
    같은 이슈로 판단된 여러 언론사의 클러스터를
    하나의 묶음으로 합치기 위한 자료구조다.
    """

    def __init__(self, size):
        self.parent = list(range(size))

    def find(self, index):
        if self.parent[index] != index:
            self.parent[index] = self.find(
                self.parent[index]
            )

        return self.parent[index]

    def union(self, first, second):
        first_root = self.find(first)
        second_root = self.find(second)

        if first_root != second_root:
            self.parent[second_root] = first_root


def load_json(path):
    """
    JSON 파일을 읽는다.
    """
    if not path.exists():
        raise FileNotFoundError(
            f"{path} 파일이 없습니다."
        )

    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def get_cluster_articles(cluster, news_items):
    """
    clusters.json에 저장된 기사 번호를 이용해
    news.json의 실제 기사 정보를 가져온다.

    article_indexes는 1부터 시작하므로
    리스트에서는 1을 빼서 사용한다.
    """
    articles = []

    for article_index in cluster.get(
        "article_indexes",
        [],
    ):
        zero_based_index = article_index - 1

        if 0 <= zero_based_index < len(news_items):
            articles.append(
                news_items[zero_based_index]
            )

    return articles

def has_shared_core_terms(first_cluster, second_cluster):
    """
    두 클러스터 대표 제목에 공통 핵심어가 있는지 확인한다.
    조사·일반 보도어를 제외한 2글자 이상 단어를 비교한다.
    """
    first_title = clean_text(
        first_cluster.get("topic_title", "")
    )
    second_title = clean_text(
        second_cluster.get("topic_title", "")
    )

    stopwords = {
        "대통령",
        "정부",
        "국민",
        "관련",
        "논란",
        "발언",
        "주문",
        "대책",
        "정치",
        "사회",
        "경제",
        "속보",
        "기자",
        "뉴스",
        "대한",
        "위해",
        "통해",
        "에서",
        "으로",
        "한다",
        "했다",
    }

    first_terms = {
        word
        for word in first_title.split()
        if len(word) >= 2
        and word not in stopwords
    }

    second_terms = {
        word
        for word in second_title.split()
        if len(word) >= 2
        and word not in stopwords
    }

    shared_terms = first_terms & second_terms

    return len(shared_terms) >= 1

def make_cluster_text(cluster, articles):
    """
    클러스터 대표 제목과 포함된 기사 제목·설명을 합쳐
    언론사 간 클러스터 유사도 계산용 텍스트를 만든다.

    대표 제목과 기사 제목을 두 번 사용해
    제목에 더 높은 비중을 준다.
    """
    topic_title = clean_text(
        cluster.get("topic_title", "")
    )

    article_parts = []

    for article in articles:
        title = clean_text(
            article.get("title", "")
        )
        description = clean_text(
            article.get("description", "")
        )

        article_parts.append(
            f"{title} {title} {description}"
        )

    return " ".join(
        [
            topic_title,
            topic_title,
            *article_parts,
        ]
    ).strip()


def prepare_clusters(cluster_data, news_items):
    """
    clusters.json의 각 클러스터에
    실제 기사 정보와 비교용 텍스트를 붙인다.
    """
    prepared_clusters = []

    for cluster in cluster_data.get(
        "clusters",
        [],
    ):
        articles = get_cluster_articles(
            cluster,
            news_items,
        )

        if not articles:
            continue

        category = cluster.get(
            "category",
            articles[0].get("category", "기타"),
        )

        publisher = cluster.get(
            "publisher",
            articles[0].get(
                "publisher",
                "언론사 미상",
            ),
        )

        prepared_clusters.append(
            {
                "cluster_id": cluster.get(
                    "cluster_id"
                ),
                "category": category,
                "publisher": publisher,
                "topic_title": cluster.get(
                    "topic_title",
                    "제목 없음",
                ),
                "article_count": len(articles),
                "article_indexes": cluster.get(
                    "article_indexes",
                    [],
                ),
                "articles": articles,
                "comparison_text": make_cluster_text(
                    cluster,
                    articles,
                ),
            }
        )

    return prepared_clusters


def compare_clusters_in_category(
    category,
    category_clusters,
):
    """
    같은 카테고리 안에서 서로 다른 언론사의
    클러스터끼리 유사도를 계산한다.
    """
    if len(category_clusters) < 2:
        return [], []

    cluster_texts = [
        cluster["comparison_text"]
        for cluster in category_clusters
    ]

    vectorizer = TfidfVectorizer(
        analyzer="char_wb",
        ngram_range=(2, 5),
        min_df=1,
        sublinear_tf=True,
    )

    tfidf_matrix = vectorizer.fit_transform(
        cluster_texts
    )

    similarity_matrix = cosine_similarity(
        tfidf_matrix
    )

    union_find = UnionFind(
        len(category_clusters)
    )

    similarity_candidates = []
    matched_pairs = []

    for first_index in range(
        len(category_clusters)
    ):
        for second_index in range(
            first_index + 1,
            len(category_clusters),
        ):
            first_cluster = category_clusters[
                first_index
            ]
            second_cluster = category_clusters[
                second_index
            ]

            # 같은 언론사에서 만들어진 클러스터끼리는
            # 이 단계에서 비교하지 않는다.
            if (
                first_cluster["publisher"]
                == second_cluster["publisher"]
            ):
                continue

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

            if (
                similarity
                >= CLUSTER_SIMILARITY_THRESHOLD
            ):
                union_find.union(
                    first_index,
                    second_index,
                )

                matched_pairs.append(
                    {
                        "category": category,
                        "first_cluster_id": (
                            first_cluster["cluster_id"]
                        ),
                        "first_publisher": (
                            first_cluster["publisher"]
                        ),
                        "second_cluster_id": (
                            second_cluster["cluster_id"]
                        ),
                        "second_publisher": (
                            second_cluster["publisher"]
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

    print(
        f"\n{category} 카테고리 "
        f"언론사 간 클러스터 유사도 TOP 10"
    )

    for (
        similarity,
        first_index,
        second_index,
    ) in similarity_candidates[:10]:
        first_cluster = category_clusters[
            first_index
        ]
        second_cluster = category_clusters[
            second_index
        ]

        print(f"\n유사도: {similarity:.3f}")

        print(
            f"[{first_cluster['publisher']}] "
            f"{first_cluster['topic_title']}"
        )

        print(
            f"[{second_cluster['publisher']}] "
            f"{second_cluster['topic_title']}"
        )

    grouped_indexes = defaultdict(list)

    for index in range(
        len(category_clusters)
    ):
        root = union_find.find(index)
        grouped_indexes[root].append(index)

    matched_groups = []

    for indexes in grouped_indexes.values():
        clusters = [
            category_clusters[index]
            for index in indexes
        ]

        publishers = sorted(
            {
                cluster["publisher"]
                for cluster in clusters
            }
        )

        # 서로 다른 언론사가 2곳 이상 포함된
        # 이슈 묶음만 결과로 남긴다.
        if len(publishers) < 2:
            continue

        cluster_ids = {
            cluster["cluster_id"]
            for cluster in clusters
        }

        group_pair_matches = [
            pair
            for pair in matched_pairs
            if (
                pair["first_cluster_id"]
                in cluster_ids
                and pair["second_cluster_id"]
                in cluster_ids
            )
        ]

        # 같은 언론사의 클러스터가 여러 개 포함되면,
        # 다른 언론사 클러스터들과의 유사도 합계가
        # 가장 높은 클러스터 하나만 남긴다.
        clusters_by_publisher = defaultdict(list)

        for cluster in clusters:
            clusters_by_publisher[
                cluster["publisher"]
            ].append(cluster)

        selected_clusters = []

        for publisher, publisher_clusters in (
            clusters_by_publisher.items()
        ):
            if len(publisher_clusters) == 1:
                selected_clusters.append(
                    publisher_clusters[0]
                )
                continue

            cluster_scores = {}

            for cluster in publisher_clusters:
                cluster_id = cluster["cluster_id"]
                score = 0.0

                for pair in group_pair_matches:
                    if (
                        pair["first_cluster_id"]
                        == cluster_id
                        or pair["second_cluster_id"]
                        == cluster_id
                    ):
                        score += pair["similarity"]

                cluster_scores[cluster_id] = score

            selected_cluster = max(
                publisher_clusters,
                key=lambda cluster: (
                    cluster_scores.get(
                        cluster["cluster_id"],
                        0.0,
                    ),
                    cluster["article_count"],
                ),
            )

            selected_clusters.append(
                selected_cluster
            )

            removed_cluster_ids = [
                cluster["cluster_id"]
                for cluster in publisher_clusters
                if (
                    cluster["cluster_id"]
                    != selected_cluster["cluster_id"]
                )
            ]

            print(
                f"\n[중복 정리] {category} / {publisher}"
            )
            print(
                f"유지: {selected_cluster['cluster_id']} / "
                f"{selected_cluster['topic_title']}"
            )
            print(
                f"제외: {removed_cluster_ids}"
            )

        clusters = selected_clusters

        publishers = sorted(
            {
                cluster["publisher"]
                for cluster in clusters
            }
        )

        cluster_ids = {
            cluster["cluster_id"]
            for cluster in clusters
        }

        group_pair_matches = [
            pair
            for pair in group_pair_matches
            if (
                pair["first_cluster_id"]
                in cluster_ids
                and pair["second_cluster_id"]
                in cluster_ids
            )
        ]

        matched_groups.append(
            {
                "category": category,
                "publisher_count": len(
                    publishers
                ),
                "publishers": publishers,
                "cluster_ids": [
                    cluster["cluster_id"]
                    for cluster in clusters
                ],
                "total_article_count": sum(
                    cluster["article_count"]
                    for cluster in clusters
                ),
                "clusters": [
                    {
                        "cluster_id": (
                            cluster["cluster_id"]
                        ),
                        "publisher": (
                            cluster["publisher"]
                        ),
                        "topic_title": (
                            cluster["topic_title"]
                        ),
                        "article_count": (
                            cluster["article_count"]
                        ),
                        "article_indexes": (
                            cluster["article_indexes"]
                        ),
                        "articles": (
                            cluster["articles"]
                        ),
                    }
                    for cluster in clusters
                ],
                "pair_matches": (
                    group_pair_matches
                ),
            }
        )

    return matched_groups, matched_pairs


def match_clusters(prepared_clusters):
    """
    카테고리별로 나눈 뒤
    서로 다른 언론사의 클러스터를 매칭한다.
    """
    clusters_by_category = defaultdict(list)

    for cluster in prepared_clusters:
        clusters_by_category[
            cluster["category"]
        ].append(cluster)

    all_matched_groups = []
    all_matched_pairs = []

    for category, category_clusters in (
        clusters_by_category.items()
    ):
        matched_groups, matched_pairs = (
            compare_clusters_in_category(
                category,
                category_clusters,
            )
        )

        all_matched_groups.extend(
            matched_groups
        )

        all_matched_pairs.extend(
            matched_pairs
        )

    # 많은 언론사가 다룬 이슈를 우선하고,
    # 그다음 기사 수가 많은 이슈를 우선한다.
    all_matched_groups.sort(
        key=lambda group: (
            group["publisher_count"],
            group["total_article_count"],
        ),
        reverse=True,
    )

    for index, matched_group in enumerate(
        all_matched_groups,
        start=1,
    ):
        matched_group["match_id"] = (
            f"match-{index}"
        )

    return all_matched_groups, all_matched_pairs


def main():
    news_items = load_json(NEWS_PATH)
    cluster_data = load_json(CLUSTERS_PATH)

    prepared_clusters = prepare_clusters(
        cluster_data,
        news_items,
    )

    matched_groups, matched_pairs = (
        match_clusters(prepared_clusters)
    )

    output_data = {
        "cluster_similarity_threshold": (
            CLUSTER_SIMILARITY_THRESHOLD
        ),
        "matched_issue_count": len(
            matched_groups
        ),
        "matched_pair_count": len(
            matched_pairs
        ),
        "matched_issues": matched_groups,
        "matched_pairs": matched_pairs,
    }

    OUTPUT_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with OUTPUT_PATH.open(
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            output_data,
            file,
            ensure_ascii=False,
            indent=2,
        )

    print(
        f"\n전체 내부 클러스터 수: "
        f"{len(prepared_clusters)}개"
    )

    print(
        f"언론사 간 유사 클러스터 쌍: "
        f"{len(matched_pairs)}개"
    )

    print(
        f"비교 가능한 공통 이슈: "
        f"{len(matched_groups)}개"
    )

    print(
        f"결과 저장 위치: {OUTPUT_PATH}"
    )

    for matched_group in matched_groups:
        print(
            f"- {matched_group['match_id']} / "
            f"{matched_group['category']} / "
            f"{' · '.join(matched_group['publishers'])} / "
            f"{matched_group['cluster_ids']}"
        )


if __name__ == "__main__":
    main()