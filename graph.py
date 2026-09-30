"""그래프 조립 (최종 설계서 D-2).

START -> 후보 선택 -> [기업 조사 | 기술·파이프라인] -> [규제 | 시장·사업화] -> 투자 판단
투자 판단 -> 적격이면 보고서 생성 / 아니면 남은 후보 확인
남은 후보 있으면 후보 선택으로, 없으면 (보고서 있음 -> END | 없음 -> 적격 없음 보고서 -> END)
"""
import importlib

from langgraph.graph import END, START, StateGraph

from state import State

# 노드 이름 -> (모듈, 함수). 담당자가 이 이름으로 만들면 자동 연결된다. (팀 합의 필요)
NODE_SOURCES = {
    "select":       ("agents.select_candidate", "select_candidate"),
    "company":      ("agents.company", "company_node"),
    "tech":         ("agents.tech_pipeline", "tech_pipeline_node"),
    "regulation":   ("agents.regulation", "regulation_node"),
    "market":       ("agents.market", "market_node"),
    "judge":        ("judge.node", "judge_node"),
    "report":       ("report.writer", "report_node"),
    "no_qualified": ("report.writer", "no_qualified_node"),
}


def load_nodes() -> dict:
    """아직 만들어지지 않은 노드는 건너뛴다. build_graph가 빠진 노드를 알려 준다."""
    nodes = {}
    for name, (module, func) in NODE_SOURCES.items():
        try:
            nodes[name] = getattr(importlib.import_module(module), func)
        except (ImportError, AttributeError):
            pass
    return nodes


def has_remaining(state: State) -> bool:
    # current_idx는 평가 중인 후보 번호(0부터)
    return state["current_idx"] + 1 < len(state["candidates"])


def route_after_judge(state: State) -> str:
    if state["verdict"] == "적격":
        return "report"
    return route_remaining(state)


def route_remaining(state: State) -> str:
    if has_remaining(state):
        return "select"
    return "end" if state.get("reports") else "no_qualified"


def build_graph(nodes: dict | None = None):
    nodes = {**load_nodes(), **(nodes or {})}
    missing = [n for n in NODE_SOURCES if n not in nodes]
    if missing:
        raise NotImplementedError(f"아직 없는 노드: {missing} (NODE_SOURCES 이름으로 만들거나 nodes로 넘기세요)")

    g = StateGraph(State)
    for name in NODE_SOURCES:
        g.add_node(name, nodes[name])

    g.add_edge(START, "select")
    g.add_edge("select", "company")           # 1단계 병렬
    g.add_edge("select", "tech")
    g.add_edge("tech", "regulation")          # 2단계 병렬: 파이프라인 목록을 받는다
    g.add_edge("tech", "market")
    g.add_edge(["company", "regulation", "market"], "judge")   # 셋이 모두 끝난 뒤 한 번

    g.add_conditional_edges("judge", route_after_judge,
                            {"report": "report", "select": "select",
                             "end": END, "no_qualified": "no_qualified"})
    g.add_conditional_edges("report", route_remaining,
                            {"select": "select", "end": END, "no_qualified": "no_qualified"})
    g.add_edge("no_qualified", END)
    # 후보 4곳 x 단계 5개 = 약 21단계로 기본 한도(25)에 가까워서 여유를 둔다
    return g.compile().with_config(recursion_limit=100)
