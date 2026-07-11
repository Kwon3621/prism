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

news_path = Path("data/news.json")

with news_path.open("r", encoding="utf-8") as file:
    news_items = json.load(file)

article_text = "\n".join(
    [
        f"{index}. 언론사: {item['publisher']}\n"
        f"제목: {item['title']}\n"
        f"요약: {item.get('summary', item.get('description', ''))}"
        for index, item in enumerate(news_items, start=1)
    ]
)

prompt = f"""
아래 기사들을 동일한 사건을 다룬 기사끼리 묶어주세요.

판단 규칙:
- 두 기사가 같은 사건으로 묶이려면 핵심 인물 또는 기관, 구체적 사건, 발생 시점이 모두 실질적으로 일치해야 합니다.
- 같은 분야이거나 비슷한 단어가 나온다는 이유만으로 묶지 마세요.
- 한 기사에만 등장하는 핵심 인물, 기관, 장소, 사건이 다른 경우 반드시 별도 그룹으로 분리하세요.
- 동일 사건인지 확신이 없으면 절대 묶지 말고 개별 그룹으로 분리하세요.
- 서로 다른 언론사의 기사가 포함된 경우에도 실제 사건이 같을 때만 묶으세요.
- 제공된 기사 정보에 없는 사실은 추가하지 마세요.
- article_indexes에는 반드시 실제로 같은 사건인 기사 번호만 넣으세요.
반드시 아래 JSON 형식으로만 답하세요.

{{
  "clusters": [
    {{
      "cluster_id": "cluster-1",
      "topic_title": "공통 사건을 설명하는 중립적인 제목",
      "article_indexes": [1, 3]
    }}
  ]
}}

기사 목록:
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

output_path = Path("data/clusters.json")

with output_path.open("w", encoding="utf-8") as file:
    json.dump(result, file, ensure_ascii=False, indent=2)

print(f"기사 군집 결과를 {output_path}에 저장했습니다.")