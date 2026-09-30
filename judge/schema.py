"""LLM 구조화 출력 스키마. 항목마다 예/아니오 4개와 근거 ID만 답한다(점수는 코드가 변환)."""
from typing import Literal

from pydantic import BaseModel, Field

from config import ITEMS

ItemCode = Literal[tuple(ITEMS)]  # type: ignore[valid-type]


class ItemAnswer(BaseModel):
    item: ItemCode = Field(description="평가 항목 코드명")
    q1_neg: bool = Field(description="① −2 기준의 나쁜 사실이 확인됐나")
    q2_pos: bool = Field(description="② +2 기준의 사실이 근거로 있나")
    q3_partial: bool = Field(description="③ +2 기준의 일부만 있거나 기업 주장만 있나")
    q4_concern: bool = Field(description="④ 우려 신호(지연 · 축소 · 분쟁 조짐)가 있나")
    evidence_ids: list[str] = Field(
        default_factory=list, description="위 답의 근거가 된 evidence id. 근거가 없으면 빈 목록"
    )
    reason: str = Field(description="근거 한 줄")


class JudgeOutput(BaseModel):
    answers: list[ItemAnswer] = Field(description="12항목 각각에 대한 답")
