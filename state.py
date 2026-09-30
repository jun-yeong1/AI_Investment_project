"""그래프 State (설계서 D-1). 누적 키는 operator.add, 나머지는 덮어쓰기."""
import operator
from typing import Annotated, Optional, TypedDict

from tools.evidence import Evidence, PipelineItem


class State(TypedDict, total=False):
    candidates: list[dict]                       # config.CANDIDATES
    current_idx: int                             # 0부터 시작
    company: dict                                # {"company_id", "name"}
    pipeline: list[PipelineItem]                 # 못 찾으면 [] 로 덮어쓴다
    evidence: Annotated[list[Evidence], operator.add]      # 누적
    scores: dict                                 # 12항목 점수·근거 상태·근거 한 줄
    total: int
    verdict: Optional[str]                       # 적격 | 보류 | 부적격
    evaluations: Annotated[list[dict], operator.add]       # 누적: 기업별 판정 요약
    reports: Annotated[list[str], operator.add]            # 누적: 기업별 PDF 경로
    report_sections: dict
    references: list[dict]

# 조사 노드는 자기가 바꾼 필드만 반환한다. 결과가 없으면 None 대신 [] 를 반환한다.
#   tech_pipeline -> {"pipeline": [...], "evidence": [...]}
#   company / regulation / market -> {"evidence": [...]}
