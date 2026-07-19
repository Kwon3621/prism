"""
A팀 Passage 모델과 B팀 Query 모델이 같은 벡터 공간을 쓰는지 확인하는 스크립트.
같은 내용 vs 관련 없는 내용의 유사도를 비교해서 판단한다.
"""
import numpy as np

from embedding import create_passage_embeddings
from query_embedding import embed_query


def cosine(a, b):
    a = np.array(a)
    b = np.array(b)
    return np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))


# 같은 내용
same_text = "한국은행이 기준금리를 동결했다"

# 관련 있는 내용 (같은 주제, 다른 표현)
related_text = "한국은행 금융통화위원회가 기준금리를 유지하기로 결정했다"

# 관련 없는 내용
unrelated_text = "손흥민이 프리미어리그 경기에서 골을 넣었다"

query_vec = embed_query(same_text)

passage_same = create_passage_embeddings([same_text])[0]
passage_related = create_passage_embeddings([related_text])[0]
passage_unrelated = create_passage_embeddings([unrelated_text])[0]

print(f"[동일 문장]     query-passage 유사도: {cosine(query_vec, passage_same):.4f}")
print(f"[관련 있는 문장] query-passage 유사도: {cosine(query_vec, passage_related):.4f}")
print(f"[관련 없는 문장] query-passage 유사도: {cosine(query_vec, passage_unrelated):.4f}")