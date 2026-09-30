"""RAG 검색 반환 타입 (초안 — RAG 팀 검토 필요)."""
from typing import Literal, TypedDict

DocType = Literal["regulation", "tech", "market"]


class RagHit(TypedDict):
    chunk_id: str
    doc: str        # 문서명
    page: int
    text: str
    score: float


# rag_search(query: str, doc_type: DocType) -> list[RagHit]
# 검색 실패·관련 없음은 예외 대신 빈 리스트 []로 알린다.
# 웹 보강 여부는 호출한 Agent가 [] 를 보고 판단한다.
