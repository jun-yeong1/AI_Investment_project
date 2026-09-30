"""근거(Evidence) 형식 — 조사 에이전트 · 투자 판단 · 보고서가 모두 이 모양으로 주고받는다.

status (근거 상태, 설계서 C절)
  확인됨      : 규제기관 · 공시 · 동료심사 논문 · 독립 언론 · 공공기관 문서 등 기업 밖 출처
  기업 주장만 : 보도자료 · 홈페이지뿐
  찾지 못함   : 검색했지만 근거 없음
  상충함      : 근거끼리 충돌
  미분류      : 아직 분류하지 않음 (웹 결과는 에이전트가 출처를 보고 정한다)
"""
import uuid
from datetime import date
from typing import Literal, TypedDict

Status = Literal["확인됨", "기업 주장만", "찾지 못함", "상충함", "미분류"]


class Evidence(TypedDict, total=False):
    id: str                  # 근거 번호. REFERENCE 번호 매길 때 쓴다
    company: str             # 평가 중인 기업. 판단 · 보고서는 이 값으로 현재 기업 근거만 거른다
    item: str                # 12항목 중 하나 또는 "시장 규모" (에이전트가 채운다)
    fact: str                # 근거 한 줄
    quote: str               # 원문 발췌 (RAG 청크 또는 웹 본문)
    status: Status
    source_type: Literal["rag", "web"]
    doc_type: str            # RAG 근거일 때: 규제 | 기술 | 시장·사업성
    title: str
    publisher: str
    url: str
    page: int | None         # RAG 문서의 쪽 (사람 기준 1부터)
    published: str           # 발행일 (YYYY 또는 YYYY-MM-DD)
    accessed: str            # 접근일 YYYY-MM-DD


def make_evidence(**fields) -> Evidence:
    """id와 접근일을 자동으로 채워 Evidence를 만든다."""
    ev: Evidence = {"id": f"E{uuid.uuid4().hex[:8]}", "accessed": date.today().isoformat(),
                    "status": "미분류", **fields}
    return ev
