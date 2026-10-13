"""그래프 State (Supervisor 패턴).

제어 메타(supervisor가 라우팅 · 종료 · 재개에 쓰는 최소치)와 작업 페이로드(조사 · 판정 · 보고 결과)를 나눈다.
결정 로그(다음 담당과 사유)는 State에 쌓지 않고 outputs/logs/<trace_id>.jsonl에 남긴다.
supervisor는 한 번에 워커 하나만 부르므로 동시 쓰기가 없다. 누적 키만 리듀서를 둔다.
"""
import operator
from typing import Annotated, Optional, TypedDict

from tools.evidence import Evidence, PipelineItem


def merge_evidence(current: list[Evidence] | None, new: list[Evidence] | None) -> list[Evidence]:
    """재작업이 같은 원문 인용을 다시 가져와도 한 번만 남긴다(멱등)."""
    merged = list(current or [])
    seen = {(e["company_id"], e["source"], e["quote"]) for e in merged}
    for evidence in new or []:
        key = (evidence["company_id"], evidence["source"], evidence["quote"])
        if key not in seen:
            seen.add(key)
            merged.append(evidence)
    return merged


def merge_dict(current: dict | None, new: dict | None) -> dict:
    return {**(current or {}), **(new or {})}


def merge_by_company(current: list[dict] | None, new: list[dict] | None) -> list[dict]:
    """같은 기업을 다시 판정하면(재개 · 재실행) 덧붙이지 않고 그 기업 결과만 바꾼다."""
    merged = {e["company_id"]: e for e in current or []}
    for evaluation in new or []:
        merged[evaluation["company_id"]] = evaluation
    return list(merged.values())


class Task(TypedDict, total=False):
    area: Optional[str]          # 조사 워커면 영역 코드, 아니면 None
    mode: str                    # initial | rework
    reason: str                  # supervisor가 이 담당을 고른 이유
    target_items: list[str]      # 재작업이면 근거가 부족한 항목 코드
    queries: list[str]           # 재작업이면 새 검색어
    pipeline: list[PipelineItem] # 규제 · 시장 워커에 넘기는 기술 워커의 물질 목록


class State(TypedDict, total=False):
    # ── 작업 페이로드 ─────────────────────────────
    candidates: list[dict]                       # config.CANDIDATES
    company: dict                                # 현재 기업 {"company_id", "name"}
    pipeline: list[PipelineItem]                 # 현재 기업의 물질 · 적응증 · 단계
    evidence: Annotated[list[Evidence], merge_evidence]    # 누적, 같은 인용은 한 번만
    scores: dict                                 # 현재 기업 12항목 점수
    total: int
    verdict: Optional[str]                       # 적격 | 보류 | 부적격
    evaluations: Annotated[list[dict], merge_by_company]   # 누적: 기업별 판정 요약 (기업당 1건)
    scores_by_company: Annotated[dict, merge_dict]         # 누적: 기업별 12항목 점수 (보고서 · 품질 평가용)
    report_sections: dict                        # 보고서 문장 단위 구조 (덮어쓰기)
    report_path: str                             # 보고서 본문은 PDF 파일, State엔 경로만
    report_pages: int
    quality: Optional[dict]                      # 최근 품질 평가 결과

    # ── 제어 메타 (조정 · 종료 · 재개) ─────────────
    trace_id: str                                # 로그 · LangSmith · 체크포인트를 잇는 상관 키
    next: str                                    # supervisor가 정한 다음 담당
    task: Task                                   # 다음 워커 지시
    current_idx: int                             # 마지막으로 선택한 후보 번호, 최초 -1
    area_status: dict                            # 현재 기업 영역별 pending | done | failed
    rework_count: dict                           # 현재 기업 영역별 재작업 횟수
    read_urls: dict                              # 현재 기업에서 영역별로 이미 읽은 URL (같은 영역 재작업 때 제외)
    step_count: Annotated[int, operator.add]     # supervisor가 워커를 부른 횟수
    max_steps: int
    report_revisions: int                        # 보고서 재작성 횟수
    status: str                                  # running | done | quality_failed
    errors: Annotated[list[dict], operator.add]  # {node, type, message, ts}
    last_error: Optional[dict]                   # 가장 최근 에러 (재개 · 재시도 판단용)

# 조사 워커는 자기가 바꾼 필드만 반환한다.
#   tech -> {"pipeline", "evidence", "read_urls", "area_status"}
#   company / regulation / market -> {"evidence", "read_urls", "area_status"}


# ── 워커별 입력 범위 (graph.py에서 add_node(input_schema=...)로 적용) ─────────────
# supervisor만 State 전체를 본다. 워커는 자기 일에 필요한 키만 받아, 다른 워커의 결과는 supervisor의 지시(task)로만 전달된다.

class TechInput(TypedDict, total=False):
    company: dict
    task: Task
    pipeline: list[PipelineItem]       # 자기 결과(물질 목록)에 이어 붙일 때만 읽는다
    evidence: list[Evidence]           # 근거 ID 연속 번호 · 같은 인용 확인용
    read_urls: dict
    area_status: dict


class ResearchInput(TypedDict, total=False):
    """기업 · 규제 · 시장 워커. 기술 워커의 물질 목록은 task.pipeline으로만 받는다."""
    company: dict
    task: Task
    evidence: list[Evidence]
    read_urls: dict
    area_status: dict


class SelectInput(TypedDict, total=False):
    candidates: list[dict]
    current_idx: int


class JudgeInput(TypedDict, total=False):
    company: dict
    evidence: list[Evidence]


class ReportInput(TypedDict, total=False):
    trace_id: str
    candidates: list[dict]
    evaluations: list[dict]
    scores_by_company: dict
    evidence: list[Evidence]
    report_sections: dict
    quality: Optional[dict]


class QualityInput(TypedDict, total=False):
    report_sections: dict
    report_pages: int
    evidence: list[Evidence]
    evaluations: list[dict]
    scores_by_company: dict
    quality: dict             # 직전 판 평가(바뀌지 않은 문장의 LLM 판정 재사용)
