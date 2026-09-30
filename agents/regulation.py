"""물질·적응증 단위 규제, 소송, 해외 진행 조사."""

from agents.common import ResearchTools, research
from config import ITEMS as RUBRIC_ITEMS
from state import State

ITEMS = tuple(item for item, (_, area, _) in RUBRIC_ITEMS.items() if area == "regulation")


def regulation_node(state: State, *, tools: ResearchTools | None = None) -> dict:
    name = state["company"]["name"]
    pipeline = state.get("pipeline", [])
    queries = [f"{name} 특허 소송 분쟁 해외 임상 해외 기술이전"]
    # 파이프라인이 있으면 회사명보다 물질명·적응증을 우선해 규제 상태를 찾는다.
    for item in pipeline:
        subject = f"{item['substance']} {item['indication']}"
        queries.extend(
            (
                f"{subject} FDA IND 식약처 임상시험계획 승인 clinical hold",
                f"{subject} FDA 희귀의약품 신속심사 지정 해외 임상",
            )
        )
    if not pipeline:
        # 기술 노드가 물질을 못 찾았더라도 규제 조사 자체는 수행한다.
        queries.append(f"{name} FDA IND 식약처 임상시험계획 승인 희귀의약품")
    return research(
        state,
        area="regulation",
        items=ITEMS,
        queries=queries,
        rag_query="FDA 신속심사 지정 요건과 IND 효력",
        include_pipeline=False,
        tools=tools,
    )


run = regulation_node
