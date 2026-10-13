"""평가 순서대로 다음 기업을 선택한다."""

from config import AREAS, CANDIDATES
from state import State


def select_candidate(state: State) -> dict:
    """current_idx는 마지막으로 선택한 기업의 0 기반 번호다. 최초 값은 -1."""
    candidates = state.get("candidates", CANDIDATES)
    index = state.get("current_idx", -1) + 1
    if index >= len(candidates):
        raise IndexError("평가할 후보가 더 없습니다")
    # 누적 evidence는 유지하고, 직전 기업에만 해당하는 값은 다음 기업으로 넘기지 않는다.
    return {
        "current_idx": index,
        "company": candidates[index],
        "pipeline": [],
        "scores": {},
        "total": 0,
        "verdict": None,
        # 조사 진행 상태도 기업 단위라 새 기업에서 처음부터 센다
        "area_status": {area: "pending" for area in AREAS},
        "rework_count": {},
        "read_urls": [],
    }


run = select_candidate
