"""근거(Evidence) 공통 타입. 조사 노드가 쓰고 투자 판단·보고서가 읽는다."""
from typing import Literal, Optional, TypedDict

EvidenceStatus = Literal["확인됨", "기업 주장만", "찾지 못함", "상충함"]


class Evidence(TypedDict):
    id: str                   # 예: "standigm-regulation-003" (채점 결과와 연결하는 키)
    company_id: str           # config.CANDIDATES의 company_id
    item: str                 # config.ITEMS의 12항목 코드명
    fact: str                 # 사실 한 줄
    quote: str                # 원문 인용
    status: EvidenceStatus
    source: str               # 웹이면 URL, RAG면 문서명
    page: Optional[int]       # RAG 문서면 쪽, 웹이면 None
    published: Optional[str]  # "YYYY-MM-DD"
    accessed: str             # "YYYY-MM-DD"


class PipelineItem(TypedDict):
    substance: str            # 물질명
    indication: str           # 적응증
    stage: str                # 개발 단계


def make_evidence_id(company_id: str, item: str, seq: int) -> str:
    return f"{company_id}-{item}-{seq:03d}"
