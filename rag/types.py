"""RAG 검색 반환 타입 (초안 — RAG 팀 검토 필요)."""
from typing import Literal, TypedDict

DocType = Literal["regulation", "tech", "market"]


class RagHit(TypedDict):
    chunk_id: str
    doc: str        # 문서명
    page: int
    text: str
    score: float


# 설계서 B-2: 관련성이 낮으면 질문을 1회 재작성하고, 그래도 낮으면 웹 검색으로 보강한다.
# rag_search의 최종 반환 타입은 웹 보강 결과 표현까지 포함해 RAG·Agent 팀이 확정한다.
