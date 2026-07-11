import json
import os
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI


load_dotenv()

client = OpenAI(
    api_key=os.getenv("UPSTAGE_API_KEY"),
    base_url="https://api.upstage.ai/v1",
)

with Path("data/news.json").open("r", encoding="utf-8") as file:
    news_items = json.load(file)

with Path("data/clusters.json").open("r", encoding="utf-8") as file:
    cluster_data = json.load(file)

selected_cluster = None

for cluster in cluster_data["clusters"]:
    articles = [
        news_items[index - 1]
        for index in cluster["article_indexes"]
        if 1 <= index <= len(news_items)
    ]

    publishers = {article["publisher"] for article in articles}

    if len(publishers) >= 2:
        selected_cluster = cluster
        selected_articles = articles
        break

if selected_cluster is None:
    raise ValueError("서로 다른 언론사가 포함된 비교 가능한 클러스터가 없습니다.")

article_text = "\n\n".join(
    [
        f"""
언론사: {article["publisher"]}
제목: {article["title"]}
RSS 요약: {article.get("summary", "")}
원문 링크: {article["link"]}
""".strip()
        for article in selected_articles
    ]
)

prompt = f"""
다음은 서로 다른 언론사가 같은 사건을 보도한 기사 정보입니다.

현재 제공되는 자료는 기사 제목과 RSS 기반 요약이므로,
자료에서 명확하게 확인되지 않는 내용은 추정하지 마세요.

분석 원칙:
- 특정 언론사가 옳거나 편향되었다고 판단하지 마세요.
- 기사에 실제로 나타난 제목과 요약 표현만 근거로 분석하세요.
- 공통 사실과 언론사별 차이를 구분하세요.
- 차이가 명확하지 않으면 "명확한 차이를 확인하기 어려움"이라고 작성하세요.
- 기자 또는 언론사의 정치적 의도를 추정하지 마세요.
- 핵심 키워드와 주요 인물은 기사 정보에 직접 등장한 것만 사용하세요.

반드시 아래 JSON 형식으로만 답하세요.

{{
  "issue_id": "{selected_cluster["cluster_id"]}",
  "category": "자동 분류한 간단한 분야",
  "title": "{selected_cluster["topic_title"]}",
  "summary": "이 사건을 중립적으로 설명하는 1~2문장",
  "common_facts": [
    "두 기사에서 공통으로 확인되는 사실"
  ],
  "articles": [
    {{
      "publisher": "언론사명",
      "title": "원래 기사 제목",
      "link": "원문 링크",
      "keywords": ["핵심 키워드"],
      "people": ["기사에 등장한 주요 인물 또는 기관"],
      "focus": "이 기사에서 상대적으로 강조된 내용",
      "expression_summary": "제목과 RSS 요약에서 확인되는 표현 방식",
      "evidence_limit": "현재 자료만으로 판단하기 어려운 부분"
    }}
  ]
}}

기사 정보:
{article_text}
"""

response = client.chat.completions.create(
    model="solar-pro3",
    messages=[
        {
            "role": "user",
            "content": prompt,
        }
    ],
    response_format={"type": "json_object"},
)

result = json.loads(response.choices[0].message.content)

output_path = Path("data/issue.json")

with output_path.open("w", encoding="utf-8") as file:
    json.dump(result, file, ensure_ascii=False, indent=2)

print(
    f"{selected_cluster['topic_title']} 비교 결과를 "
    f"{output_path}에 저장했습니다."
)