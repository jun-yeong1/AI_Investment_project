"""물질·적응증 단위 시장, 경쟁, 사업화와 투자금 회수 조사."""

from agents.common import ResearchTools, research
from config import ITEMS as RUBRIC_ITEMS
from state import State

ITEMS = tuple(item for item, (_, area, _) in RUBRIC_ITEMS.items() if area == "market")


def market_node(state: State, *, tools: ResearchTools | None = None) -> dict:
    name = state["company"]["name"]
    pipeline = state.get("pipeline", [])
    queries = [f"{name} 기술이전 계약금 공동연구 파트너 상장 기술성평가"]
    # 시장 규모와 경쟁 약물은 파이프라인의 적응증별로 확인한다.
    for item in pipeline:
        subject = f"{item['substance']} {item['indication']}"
        queries.extend((f"{subject} 시장 규모 환자 수", f"{subject} 경쟁 약물 치료제 차별성"))
    if not pipeline:
        # 물질 정보가 없으면 회사 단위 검색으로 조사 공백을 최소화한다.
        queries.append(f"{name} 적응증 시장 규모 경쟁 약물")
    return research(
        state,
        area="market",
        items=ITEMS,
        queries=queries,
        rag_query="신약 임상 성공률과 기술특례상장 요건",
        include_pipeline=False,
        tools=tools,
    )


run = market_node
