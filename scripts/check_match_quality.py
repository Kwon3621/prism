import json
from pathlib import Path
from statistics import mean, median


INPUT_PATH = Path("data/matched_clusters.json")


def load_matched_issues():
    with INPUT_PATH.open("r", encoding="utf-8") as file:
        data = json.load(file)

    return data.get("matched_issues", [])


def calculate_issue_metrics(issue):
    pair_matches = issue.get("pair_matches", [])

    similarities = [
        pair.get("similarity")
        for pair in pair_matches
        if isinstance(pair.get("similarity"), (int, float))
    ]

    if similarities:
        max_similarity = max(similarities)
        average_similarity = mean(similarities)
        min_similarity = min(similarities)
        median_similarity = median(similarities)
    else:
        max_similarity = 0
        average_similarity = 0
        min_similarity = 0
        median_similarity = 0

    titles = []

    for cluster in issue.get("clusters", []):
        publisher = cluster.get("publisher", "알 수 없음")
        topic_title = cluster.get("topic_title", "")
        titles.append(f"{publisher}: {topic_title}")

    return {
        "match_id": issue.get("match_id", "unknown"),
        "category": issue.get("category", "기타"),
        "publisher_count": issue.get("publisher_count", 0),
        "article_count": issue.get("total_article_count", 0),
        "pair_count": len(similarities),
        "max_similarity": max_similarity,
        "average_similarity": average_similarity,
        "median_similarity": median_similarity,
        "min_similarity": min_similarity,
        "titles": titles,
    }


def classify_quality(metrics):
    max_similarity = metrics["max_similarity"]
    average_similarity = metrics["average_similarity"]
    min_similarity = metrics["min_similarity"]
    publisher_count = metrics["publisher_count"]

    if (
        max_similarity >= 0.45
        and average_similarity >= 0.32
        and publisher_count >= 3
    ):
        return "높음"

    if (
        max_similarity >= 0.30
        and average_similarity >= 0.25
    ):
        return "보통"

    if (
        max_similarity >= 0.24
        and average_similarity >= 0.22
    ):
        return "검토 필요"

    return "낮음"


def print_issue(metrics):
    quality = classify_quality(metrics)

    print("=" * 90)
    print(
        f"{metrics['match_id']} | "
        f"{metrics['category']} | "
        f"품질: {quality}"
    )

    print(
        f"언론사 {metrics['publisher_count']}개 | "
        f"기사 {metrics['article_count']}개 | "
        f"비교쌍 {metrics['pair_count']}개"
    )

    print(
        f"최대 {metrics['max_similarity']:.3f} | "
        f"평균 {metrics['average_similarity']:.3f} | "
        f"중앙값 {metrics['median_similarity']:.3f} | "
        f"최소 {metrics['min_similarity']:.3f}"
    )

    print("- 제목")

    for title in metrics["titles"]:
        print(f"  · {title}")


def main():
    issues = load_matched_issues()

    metrics_list = [
        calculate_issue_metrics(issue)
        for issue in issues
    ]

    metrics_list.sort(
        key=lambda item: item["average_similarity"],
        reverse=True,
    )

    quality_counts = {
        "높음": 0,
        "보통": 0,
        "검토 필요": 0,
        "낮음": 0,
    }

    for metrics in metrics_list:
        quality = classify_quality(metrics)
        quality_counts[quality] += 1
        print_issue(metrics)

    print("\n" + "#" * 90)
    print("전체 요약")
    print(f"전체 공통 이슈: {len(metrics_list)}개")

    for label, count in quality_counts.items():
        print(f"{label}: {count}개")


if __name__ == "__main__":
    main()