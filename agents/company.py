"""경영진·자금 조달·평판 조사."""

from datetime import date

from agents.common import ResearchTools, research
from config import FUNDING_WINDOW_YEARS, ITEMS as RUBRIC_ITEMS
from state import State

ITEMS = tuple(item for item, (_, area, _) in RUBRIC_ITEMS.items() if area == "company")


def company_node(state: State, *, tools: ResearchTools | None = None) -> dict:
    name = state["company"]["name"]
    recent_year = date.today().year - FUNDING_WINDOW_YEARS
    # 창업 전 경력, 최근 후속 투자, 공신력 있는 평판을 서로 다른 항목으로 조사한다.
    queries = (
        f"{name} 창업자 학위 논문 제약사 경력 핵심 인력 영입",
        f"{name} {recent_year} 이후 투자 유치 후속 투자 금액 구조조정",
        f"{name} 정부 과제 선정 수상 연구 부정 논란",
    )
    return research(
        state,
        area="company",
        items=ITEMS,
        queries=queries,
        rag_query=None,
        include_pipeline=False,
        tools=tools,
    )


run = company_node
