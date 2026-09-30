"""가짜 조사 · 보고서 노드로 흐름 검증. 투자 판단은 실제 scorer를 쓰고 LLM만 대신한다."""
import config
from graph import build_graph
from judge.node import summarize


def make_nodes(qualified_ids, log):
    def select(state):
        idx = state["current_idx"] + 1
        return {"current_idx": idx, "company": state["candidates"][idx]}

    def ev(state, item, status="확인됨"):
        c = state["company"]["company_id"]
        return {"id": f"{c}-{item}", "company_id": c, "item": item, "fact": "f", "quote": "",
                "status": status, "source": "s", "page": None, "published": None, "accessed": "d"}

    def company(state):
        return {"evidence": [ev(state, i) for i in ("management", "funding", "reputation")
                             if state["company"]["company_id"] in qualified_ids]}

    def tech(state):
        items = ("stage", "manufacturing", "technology")
        ok = state["company"]["company_id"] in qualified_ids
        # 못 찾으면 빈 목록을 반환해 이전 기업 값이 남지 않게 한다(설계서 D-1)
        pipeline = [{"substance": "s", "indication": "i", "stage": "1상"}] if ok else [{"substance": "x", "indication": "i", "stage": "발굴"}]
        return {"pipeline": pipeline,
                "evidence": [ev(state, i) for i in items if ok]}

    def regulation(state):
        assert state["pipeline"], "규제는 기술·파이프라인의 pipeline을 받아야 한다"
        ok = state["company"]["company_id"] in qualified_ids
        return {"evidence": [ev(state, i) for i in ("regulation", "litigation", "overseas") if ok]}

    def market(state):
        assert state["pipeline"]
        ok = state["company"]["company_id"] in qualified_ids
        return {"evidence": [ev(state, i) for i in ("sales", "competition", "exit") if ok]}

    def judge(state):
        c = state["company"]
        mine = [e for e in state["evidence"] if e["company_id"] == c["company_id"]]
        by_item = {e["item"]: e for e in mine}
        answers = [{"item": code, "q1_neg": False, "q2_pos": code in by_item, "q3_partial": False,
                    "q4_concern": False, "evidence_ids": [by_item[code]["id"]] if code in by_item else [],
                    "reason": "r"} for code in config.ITEMS]
        return summarize(c, answers, mine)

    def report(state):
        log.append(("report", state["company"]["company_id"]))
        return {"reports": [f"{state['company']['company_id']}.pdf"]}

    def no_qualified(state):
        log.append(("no_qualified", None))
        return {}

    return {"select": select, "company": company, "tech": tech, "regulation": regulation,
            "market": market, "judge": judge, "report": report, "no_qualified": no_qualified}


def run(qualified_ids):
    log = []
    graph = build_graph(make_nodes(qualified_ids, log))
    state = graph.invoke({"candidates": config.CANDIDATES, "current_idx": -1})
    return state, log


def test_qualified_company_continues_to_next_candidate():
    state, log = run({"galux"})
    # 적격이 나와도 4곳 모두 평가한다
    assert [e["company_id"] for e in state["evaluations"]] == [c["company_id"] for c in config.CANDIDATES]
    assert [e["verdict"] for e in state["evaluations"]] == ["보류", "보류", "적격", "보류"]
    assert log == [("report", "galux")]
    assert state["reports"] == ["galux.pdf"]


def test_no_qualified_writes_no_qualified_report():
    state, log = run(set())
    assert len(state["evaluations"]) == 4
    assert all(e["verdict"] == "보류" for e in state["evaluations"])
    assert log == [("no_qualified", None)]


def test_judge_uses_only_current_company_evidence():
    state, _ = run({"standigm", "galux"})
    verdicts = {e["company_id"]: e["verdict"] for e in state["evaluations"]}
    assert verdicts["standigm"] == "적격" and verdicts["diagen"] == "보류" and verdicts["galux"] == "적격"


def test_missing_nodes_are_reported(monkeypatch):
    import pytest
    import graph
    monkeypatch.setattr(graph, "load_nodes", lambda: {})
    with pytest.raises(NotImplementedError):
        build_graph({})
