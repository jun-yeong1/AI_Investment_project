"""기술 검증·사업 단계·제조와 물질별 파이프라인 조사."""

from agents.common import ResearchTools, research
from config import ITEMS as RUBRIC_ITEMS
from state import State

ITEMS = tuple(item for item, (_, area, _) in RUBRIC_ITEMS.items() if area == "tech")


def tech_pipeline_node(state: State, *, tools: ResearchTools | None = None) -> dict:
    name = state["company"]["name"]
    # RAG는 검증 기준만 제공한다. 기업의 파이프라인 사실은 웹 원문에서 추출한다.
    return research(
        state,
        area="tech",
        items=ITEMS,
        queries=(
            f"{name} 파이프라인 후보물질 적응증 전임상 임상 첫 투여",
            f"{name} AI 신약 연구 결과 동료심사 논문 실험 데이터",
            f"{name} GMP CDMO 위탁생산 계약 품질",
        ),
        rag_query="AI 신약 발굴 물질의 검증 수준과 임상 성공률",
        include_pipeline=True,
        tools=tools,
    )


run = tech_pipeline_node
