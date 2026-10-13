"""그래프 조립 (Supervisor 패턴).

START -> supervisor -> (add_conditional_edges: state["next"]) -> 워커 하나 -> supervisor -> ... -> END
- 모든 워커는 supervisor로만 돌아온다. 워커끼리 연결된 엣지는 없다.
- 순서는 코드에 없다. supervisor가 근거 충분성 · 영역 상태를 보고 매번 다음 담당을 정한다.
"""
import importlib

from langgraph.graph import END, START, StateGraph

from state import (JudgeInput, QualityInput, ReportInput, ResearchInput, SelectInput, State,
                   TechInput)

# 노드 이름 -> (모듈, 함수)
NODE_SOURCES = {
    "supervisor": ("agents.supervisor", "supervisor_node"),
    "select":     ("agents.select_candidate", "select_candidate"),
    "company":    ("agents.company", "company_node"),
    "tech":       ("agents.tech_pipeline", "tech_pipeline_node"),
    "regulation": ("agents.regulation", "regulation_node"),
    "market":     ("agents.market", "market_node"),
    "judge":      ("judge.node", "judge_node"),
    "report":     ("report.writer", "report_node"),
    "quality":    ("quality.evaluator", "quality_node"),
}
WORKERS = [name for name in NODE_SOURCES if name != "supervisor"]
# 워커가 받는 State 범위. supervisor는 전체를 본다(입력 범위 없음)
INPUT_SCHEMAS = {
    "select": SelectInput,
    "company": ResearchInput,
    "tech": TechInput,
    "regulation": ResearchInput,
    "market": ResearchInput,
    "judge": JudgeInput,
    "report": ReportInput,
    "quality": QualityInput,
}
# 기업당 최대 약 10단계 x 4곳 + 보고서 · 품질 루프, supervisor 왕복까지 2배. 실제 종료는 State의 max_steps가 보장한다
RECURSION_LIMIT = 300


def load_nodes() -> dict:
    nodes = {}
    for name, (module, func) in NODE_SOURCES.items():
        nodes[name] = getattr(importlib.import_module(module), func)
    return nodes


def route(state: State) -> str:
    return state["next"]


def build_graph(nodes: dict | None = None, checkpointer=None):
    nodes = {**(load_nodes() if nodes is None or set(nodes) != set(NODE_SOURCES) else {}), **(nodes or {})}

    g = StateGraph(State)
    for name in NODE_SOURCES:
        g.add_node(name, nodes[name], input_schema=INPUT_SCHEMAS.get(name))

    g.add_edge(START, "supervisor")
    g.add_conditional_edges("supervisor", route, {**{name: name for name in WORKERS}, "FINISH": END})
    for name in WORKERS:
        g.add_edge(name, "supervisor")
    return g.compile(checkpointer=checkpointer).with_config(recursion_limit=RECURSION_LIMIT)
