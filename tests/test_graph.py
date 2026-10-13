"""가짜 워커로 Supervisor 흐름을 검증한다. supervisor의 충분성 · 허용 행동 · 가드는 실제 코드, LLM 선택만 대신한다."""
import config
from agents.supervisor import Decision, allowed_actions, sufficiency, supervisor_node
from graph import WORKERS, build_graph
from judge.node import summarize

AREA_ITEMS = {area: [c for c, (_, a, _) in config.ITEMS.items() if a == area] for area in config.AREAS}


def first_allowed(state, suff, allowed, why):
    """LLM 대신: 허용 행동의 첫 번째를 고르고, 재작업이면 검색어를 준다."""
    return Decision(next=allowed[0], reason="테스트", queries=[f"재작업 {allowed[0]}"])


def make_nodes(plan, log, *, quality_fail_until=1):
    """plan[company_id][area] = (첫 조사 상태, 재작업 상태). 상태가 None이면 근거 없음, 'error'면 예외."""

    def research(area):
        def node(state):
            cid = state["company"]["company_id"]
            rework = state.get("task", {}).get("mode") == "rework"
            log.append((cid, area, "rework" if rework else "initial"))
            outcome = plan.get(cid, {}).get(area, (None, None))[1 if rework else 0]
            status = dict(state.get("area_status", {}))
            if outcome == "error":
                status[area] = "failed"
                return {"area_status": status, "errors": [{"node": area, "type": "ValueError",
                                                           "message": "검색 실패", "ts": "t"}]}
            status[area] = "done"
            evidence = [] if outcome is None else [{
                "id": f"{cid}-{item}-{'r' if rework else 'i'}", "company_id": cid, "item": item,
                "fact": "f", "quote": f"{item}-{rework}", "status": outcome, "source": f"https://{area}.example/{rework}",
                "page": None, "published": None, "accessed": "d"} for item in AREA_ITEMS[area]]
            update = {"area_status": status, "evidence": evidence}
            if area == "tech":
                update["pipeline"] = [{"substance": "s", "indication": "i", "stage": "1상"}]
            return update
        return node

    def select(state):
        idx = state["current_idx"] + 1
        return {"current_idx": idx, "company": state["candidates"][idx],
                "area_status": {a: "pending" for a in config.AREAS}, "rework_count": {}, "pipeline": []}

    def judge(state):
        c = state["company"]
        mine = [e for e in state["evidence"] if e["company_id"] == c["company_id"]]
        by_item = {}
        for e in mine:
            by_item.setdefault(e["item"], []).append(e["id"])
        answers = [{"item": code, "q1_neg": False, "q2_pos": code in by_item, "q3_partial": False,
                    "q4_concern": False, "evidence_ids": by_item.get(code, []),
                    "reason": "r"} for code in config.ITEMS]
        return summarize(c, answers, mine)

    def report(state):
        revision = state["report_sections"]["revision"] + 1 if state.get("report_sections") else 0
        log.append(("report", revision))
        return {"report_sections": {"revision": revision}, "report_path": "r.pdf", "report_pages": 3,
                "report_revisions": revision}

    def quality(state):
        revision = state["report_sections"]["revision"]
        passed = revision >= quality_fail_until
        log.append(("quality", passed))
        return {"quality": {"passed": passed, "revision": revision, "summary": "테스트"}}

    nodes = {area: research(area) for area in config.AREAS}
    nodes.update(select=select, judge=judge, report=report, quality=quality,
                 supervisor=lambda state: supervisor_node(state, choose=first_allowed))
    return nodes


def run(plan, *, max_steps=config.MAX_STEPS, quality_fail_until=1):
    log = []
    graph = build_graph(make_nodes(plan, log, quality_fail_until=quality_fail_until))
    state = graph.invoke({"trace_id": "test", "candidates": config.CANDIDATES, "current_idx": -1,
                          "evidence": [], "evaluations": [], "step_count": 0, "max_steps": max_steps,
                          "report_revisions": 0})
    return state, log


OK = ("확인됨", "확인됨")


def test_workers_only_talk_to_supervisor():
    graph = build_graph(make_nodes({}, []))
    edges = graph.get_graph().edges
    for edge in edges:
        if edge.source in WORKERS:
            assert edge.target == "supervisor", f"{edge.source} -> {edge.target}"
    assert all(edge.source in ("__start__", "supervisor") or edge.target == "supervisor" for edge in edges)


def test_rework_only_where_evidence_is_short_and_steps_differ_by_company():
    plan = {
        "standigm": {a: OK for a in config.AREAS},                                   # 충분 → 재작업 없음
        "diagen": {**{a: OK for a in config.AREAS}, "regulation": ("기업 주장만", "확인됨")},  # 규제만 재작업
        "galux": {**{a: OK for a in config.AREAS}, "tech": ("error", "error")},      # 실패 → 1회 재시도 후 판정
        "drnoah": {},                                                                # 근거 없음 → 4영역 재작업
    }
    state, log = run(plan)
    research = [entry for entry in log if len(entry) == 3]
    reworks = {cid: [area for c, area, mode in research if c == cid and mode == "rework"]
               for cid in ("standigm", "diagen", "galux", "drnoah")}
    assert reworks["standigm"] == []
    assert reworks["diagen"] == ["regulation"]
    assert reworks["galux"] == ["tech"]
    # 4영역 모두 부족해도 기업당 예산(2회) 안에서만 재작업한다
    assert len(reworks["drnoah"]) == config.MAX_REWORK_PER_COMPANY
    verdicts = {e["company_id"]: e["verdict"] for e in state["evaluations"]}
    assert verdicts["standigm"] == "적격" and verdicts["diagen"] == "적격"
    assert verdicts["drnoah"] == "보류"
    assert len(state["evaluations"]) == 4
    assert state["errors"], "실패한 조사는 에러로 남는다"


def test_regulation_and_market_wait_for_tech():
    log = []
    run_plan = {c["company_id"]: {a: OK for a in config.AREAS} for c in config.CANDIDATES}
    graph = build_graph(make_nodes(run_plan, log))
    graph.invoke({"trace_id": "test", "candidates": config.CANDIDATES, "current_idx": -1, "evidence": [],
                  "evaluations": [], "step_count": 0, "max_steps": config.MAX_STEPS, "report_revisions": 0})
    for cid in run_plan:
        order = [area for c, area, _ in (entry for entry in log if len(entry) == 3) if c == cid]
        assert order.index("tech") < order.index("regulation")
        assert order.index("tech") < order.index("market")


def test_quality_loop_rewrites_report_until_pass():
    state, log = run({}, quality_fail_until=1)
    assert [entry for entry in log if entry[0] in ("report", "quality")] == [
        ("report", 0), ("quality", False), ("report", 1), ("quality", True)]
    assert state["status"] == "done"


def test_quality_failure_stops_at_revision_limit():
    state, log = run({}, quality_fail_until=99)
    assert sum(1 for entry in log if entry[0] == "report") == config.MAX_REPORT_REVISIONS + 1
    assert state["status"] == "quality_failed"


def test_step_limit_still_finishes_every_company():
    state, log = run({}, max_steps=4)
    assert len(state["evaluations"]) == 4
    assert state["status"] in ("done", "quality_failed")
    assert not any(mode == "rework" for _, _, mode in [e for e in log if len(e) == 3])


def test_judge_not_allowed_while_gap_and_budget_remain():
    state = {"candidates": config.CANDIDATES, "company": config.CANDIDATES[0], "evaluations": [],
             "area_status": {a: "done" for a in config.AREAS}, "rework_count": {}, "evidence": [],
             "step_count": 0, "max_steps": config.MAX_STEPS}
    allowed, _ = allowed_actions(state, sufficiency(state))
    assert "judge" not in allowed and set(allowed) == set(config.AREAS)
    state["rework_count"] = {"tech": 1, "regulation": 1}
    assert allowed_actions(state, sufficiency(state))[0] == ["judge"]


def test_guard_overrides_choice_outside_allowed():
    state = {"trace_id": "test", "candidates": config.CANDIDATES, "company": config.CANDIDATES[0],
             "evaluations": [], "area_status": {a: "pending" for a in config.AREAS}, "evidence": [],
             "step_count": 0, "max_steps": config.MAX_STEPS}
    update = supervisor_node(state, choose=lambda *a: Decision(next="report", reason="건너뛰기"))
    assert update["next"] in ("company", "tech")


def test_resume_from_checkpoint_after_crash():
    """워커가 예외로 멈춰도 같은 thread_id로 이어 실행하면 끝난 단계는 다시 하지 않고 마저 끝난다(--resume과 같은 경로)."""
    from langgraph.checkpoint.sqlite import SqliteSaver

    log = []
    nodes = make_nodes({c["company_id"]: {a: OK for a in config.AREAS} for c in config.CANDIDATES}, log)
    real_market = nodes["market"]
    crashed = []

    def market_once_broken(state):
        if state["company"]["company_id"] == "diagen" and not crashed:
            crashed.append(True)
            raise ConnectionError("네트워크 끊김")
        return real_market(state)

    nodes["market"] = market_once_broken
    config_ = {"configurable": {"thread_id": "resume-test"}}
    start = {"trace_id": "resume-test", "candidates": config.CANDIDATES, "current_idx": -1, "evidence": [],
             "evaluations": [], "step_count": 0, "max_steps": config.MAX_STEPS, "report_revisions": 0}
    with SqliteSaver.from_conn_string(":memory:") as saver:
        graph = build_graph(nodes, checkpointer=saver)
        try:
            graph.invoke(start, config_)
            raise AssertionError("첫 실행은 중간에 멈춰야 한다")
        except ConnectionError:
            pass
        done_before = [entry for entry in log if len(entry) == 3]
        assert len(graph.get_state(config_).values["evaluations"]) == 1   # 스탠다임까지만 판정
        final = graph.invoke(None, config_)                               # --resume
    research = [entry for entry in log if len(entry) == 3]
    assert len(final["evaluations"]) == 4 and final["status"] == "done"
    # 멈추기 전에 끝난 조사는 다시 하지 않는다(스탠다임 4영역은 한 번씩만)
    assert sum(1 for c, *_ in research if c == "standigm") == 4
    assert research[:len(done_before)] == done_before


def test_rebuild_report_reruns_only_report_stage():
    """끝난 실행에서 보고서 · 품질 단계만 다시 돈다(--rebuild-report). 조사 · 판정은 반복하지 않는다."""
    from langgraph.checkpoint.sqlite import SqliteSaver

    from app import reset_report_stage

    log = []
    nodes = make_nodes({c["company_id"]: {a: OK for a in config.AREAS} for c in config.CANDIDATES}, log)
    config_ = {"configurable": {"thread_id": "rebuild-test"}}
    start = {"trace_id": "rebuild-test", "candidates": config.CANDIDATES, "current_idx": -1, "evidence": [],
             "evaluations": [], "step_count": 0, "max_steps": config.MAX_STEPS, "report_revisions": 0}
    with SqliteSaver.from_conn_string(":memory:") as saver:
        graph = build_graph(nodes, checkpointer=saver)
        first = graph.invoke(start, config_)
        research = [entry for entry in log if len(entry) == 3]
        reports = [entry for entry in log if entry[0] == "report"]
        reset_report_stage(graph, config_)
        final = graph.invoke(None, config_)
        reset_report_stage(graph, config_)                   # 여러 번 다시 만들어도 단계 수가 쌓이지 않는다
        again = graph.invoke(None, config_)
    assert first["status"] == "done" and final["status"] == "done" and again["status"] == "done"
    assert first["step_count"] == final["step_count"] == again["step_count"]
    assert [entry for entry in log if len(entry) == 3] == research          # 조사 반복 없음
    assert len([entry for entry in log if entry[0] == "report"]) > len(reports)
    assert final["evaluations"] == first["evaluations"]
