"""보고서 품질 평가. LLM · 네트워크 없이 가짜 judge를 주입해 규칙과 판정 로직을 검증한다."""
import copy

import pytest

from config import ITEMS, JUDGE_PROVIDER, MAX_REPORT_PAGES
from quality.evaluator import (MAX_LINES_PER_CALL, PROMPT_PATH, LineJudgment, QualityJudgeOutput,
                               evaluate, llm_judge, quality_node)

NAMES = {"standigm": "스탠다임", "diagen": "디어젠"}


def ev(id_, company_id, source, status="확인됨"):
    return {"id": id_, "company_id": company_id, "item": "management", "fact": f"{id_} 사실",
            "quote": f"{id_} 원문 인용", "status": status, "source": source, "page": None,
            "published": None, "accessed": "2026-10-01", "title": None}


def line(id_, text, *, kind="fact", company_id=None, evidence_ids=(), citations=()):
    return {"id": id_, "kind": kind, "company_id": company_id, "text": text,
            "evidence_ids": list(evidence_ids), "citations": list(citations)}


def reference(number, source, evidence_ids=()):
    return {"number": number, "source": source, "page": None, "published": None,
            "accessed": "2026-10-01", "title": None, "evidence_ids": list(evidence_ids)}


def make_evidence():
    return [
        ev("standigm-1", "standigm", "https://www.alpha.com/a"),
        {**ev("standigm-2", "standigm", "https://beta.org/b"), "quote": "standigm-2 원문 인용: 2024년 시리즈A 투자"},
        {**ev("diagen-1", "diagen", "https://gamma.com/c"), "quote": "diagen-1 원문 인용: 2023년 설립"},
        ev("diagen-2", "diagen", "https://delta.net/d"),
    ]


def make_evaluations():
    gates = {"technology": {"name": "기술", "status": "확인됨", "score": 2, "ok": True},
             "regulation": {"name": "법률·정책", "status": "확인됨", "score": 1, "ok": True}}
    return [{"company_id": company_id, "name": name, "total": 7, "score100": 64.6,
             "verdict": "적격", "gates": copy.deepcopy(gates)} for company_id, name in NAMES.items()]


def make_scores(**overrides):
    scores = {code: {"score": 1, "status": "확인됨", "evidence_ids": [], "reason": ""} for code in ITEMS}
    for code, score in overrides.items():
        scores[code]["score"] = score
    return scores


def make_sections():
    """기업 2곳, 기업마다 출처 도메인 2개. 모든 규칙을 통과하는 보고서."""
    return {
        "title": "AI 신약개발 스타트업 투자 심사 보고서",
        "revision": 0,
        "summary": [
            line("sum-001", "스탠다임 | 적격 | 합계 +7점 | 환산 64.6/100점", kind="note", company_id="standigm"),
            line("sum-002", "디어젠 | 적격 | 합계 +7점 | 환산 64.6/100점", kind="note", company_id="diagen"),
        ],
        "chapters": [
            {"key": "chapter1", "title": "1. 기업 개요와 팀", "lines": [
                line("ch1-001", "스탠다임 창업자는 제약사 연구소 출신이다. [1]",
                     company_id="standigm", evidence_ids=["standigm-1"], citations=[1]),
                line("ch1-002", "스탠다임은 2024년 시리즈A 투자를 받았다. [2]",
                     company_id="standigm", evidence_ids=["standigm-2"], citations=[2]),
                line("ch1-003", "디어젠은 2023년에 설립됐다. [3]",
                     company_id="diagen", evidence_ids=["diagen-1"], citations=[3]),
            ]},
            {"key": "chapter2", "title": "2. 시장 · 경쟁 리스크", "lines": [
                line("ch2-001", "디어젠은 해외 제약사와 공동연구를 시작했다. [4]",
                     company_id="diagen", evidence_ids=["diagen-2"], citations=[4]),
            ]},
            {"key": "chapter3", "title": "3. 기술 · 규제 리스크", "lines": [
                line("ch3-001", "관문: 기술 +2점/확인됨", kind="note", company_id="standigm"),
            ]},
            {"key": "chapter4", "title": "4. 리스크 종합과 투자 판단",
             "table": [{"item": "스탠다임", "score": 7, "status": "적격", "citation": "64.6/100"},
                       {"item": "디어젠", "score": 7, "status": "적격", "citation": "64.6/100"}],
             "lines": [line("ch4-001", "판정 기준: 합계 +5점 이상, 관문 · 영역 조건 충족", kind="note")]},
            {"key": "chapter5", "title": "5. 한계점", "lines": [
                line("ch5-001", "비상장 기업은 공개 자료가 제한된다.", kind="note"),
            ]},
        ],
        "references": [
            reference(1, "https://www.alpha.com/a", ["standigm-1"]),
            reference(2, "https://beta.org/b", ["standigm-2"]),
            reference(3, "https://gamma.com/c", ["diagen-1"]),
            reference(4, "https://delta.net/d", ["diagen-2"]),
        ],
    }


def find(sections, line_id):
    parts = [sections["summary"]] + [c["lines"] for c in sections["chapters"]]
    return next(item for part in parts for item in part if item["id"] == line_id)


def chapter(sections, key):
    return next(c for c in sections["chapters"] if c["key"] == key)


def make_judge(*, unsupported=(), not_neutral=(), calls=None):
    """지정한 line_id만 미달로 판정하는 가짜 judge. calls에 받은 문장 묶음을 쌓는다."""
    def judge(items):
        if calls is not None:
            calls.append(items)
        flagged = {*unsupported, *not_neutral}
        return QualityJudgeOutput(judgments=[
            LineJudgment(
                line_id=item["line_id"], reason=f"{item['line_id']} 판정",
                supported=None if item["kind"] == "note" else item["line_id"] not in unsupported,
                neutral=item["line_id"] not in not_neutral,
                suggestion="고칠 방향" if item["line_id"] in flagged else "")
            for item in items])
    return judge


def run(sections=None, evidence=None, evaluations=None, pages=8, judge=None, **kwargs):
    return evaluate(
        make_sections() if sections is None else sections,
        make_evidence() if evidence is None else evidence,
        make_evaluations() if evaluations is None else evaluations,
        pages, judge=judge or make_judge(), **kwargs)


def failed_checks(result):
    return {name for name, check in result["checks"].items() if not check["passed"]}


# ---------- 통과 · 입력 ----------

def test_clean_report_passes():
    result = run()
    assert result["passed"] is True
    assert failed_checks(result) == set()
    assert set(result["checks"]) == {"groundedness", "neutrality", "bias", "format"}
    assert result["flagged_lines"] == []
    assert result["summary"] == "4개 항목 모두 통과"


def test_result_carries_report_revision():
    sections = make_sections()
    sections["revision"] = 2
    assert run(sections)["revision"] == 2


def test_revision_is_echoed_as_is():
    # supervisor가 quality["revision"] != report_sections.get("revision")으로 재평가 여부를 정한다.
    # 기본값을 끼워 넣으면 revision이 없는 보고서에서 끝없이 재평가한다
    sections = make_sections()
    del sections["revision"]
    assert run(sections)["revision"] is None


def test_evaluate_does_not_modify_inputs():
    sections, evidence, evaluations = make_sections(), make_evidence(), make_evaluations()
    before = copy.deepcopy((sections, evidence, evaluations))
    evaluate(sections, evidence, evaluations, 8, judge=make_judge())
    assert (sections, evidence, evaluations) == before


def test_judge_gets_fact_lines_and_summary_chapter4_notes_only():
    calls = []
    run(judge=make_judge(calls=calls))
    assert len(calls) == 1  # 문장이 적으면 한 번에 보낸다
    items = {item["line_id"]: item for item in calls[0]}
    # ch3-001 · ch5-001은 코드가 만든 note라 보내지 않는다
    assert set(items) == {"sum-001", "sum-002", "ch1-001", "ch1-002", "ch1-003", "ch2-001", "ch4-001"}
    assert items["ch1-001"]["kind"] == "fact" and items["ch1-001"]["company"] == "스탠다임"
    assert items["ch1-001"]["text"] == "스탠다임 창업자는 제약사 연구소 출신이다. [1]"
    assert items["ch1-001"]["evidence"] == [{
        "id": "standigm-1", "quote": "standigm-1 원문 인용", "status": "확인됨",
        "source": "https://www.alpha.com/a"}]
    assert items["ch4-001"]["kind"] == "note" and items["ch4-001"]["evidence"] == []


# ---------- 근거성 (규칙) ----------

@pytest.mark.parametrize("mutate, expected", [
    pytest.param(lambda s: find(s, "ch1-001").update(evidence_ids=[]),
                 "evidence_ids가 비어 있음", id="evidence_ids 없음"),
    pytest.param(lambda s: find(s, "ch1-001").update(evidence_ids=["nope"]),
                 "evidence에 없는 id: nope", id="없는 evidence id"),
    pytest.param(lambda s: find(s, "ch1-001").update(citations=[]),
                 "citations가 비어 있음", id="citations 없음"),
    pytest.param(lambda s: find(s, "ch1-001").update(citations=[2]),
                 "citations [2]", id="본문 [1]과 citations [2] 불일치"),
    pytest.param(lambda s: find(s, "ch1-001").update(
                     text="스탠다임 창업자는 제약사 연구소 출신이다. [9]", citations=[9]),
                 "참고문헌에 없는 번호 [9]", id="references에 없는 번호"),
])
def test_groundedness_rules(mutate, expected):
    sections = make_sections()
    mutate(sections)
    result = run(sections)
    assert "groundedness" in failed_checks(result) and result["passed"] is False
    issues = result["checks"]["groundedness"]["issues"]
    assert any(i["line_id"] == "ch1-001" and i["method"] == "rule" and expected in i["reason"]
               for i in issues)


def test_unused_reference_fails_groundedness():
    sections = make_sections()
    sections["references"].append(reference(5, "https://epsilon.io/e"))
    result = run(sections)
    assert failed_checks(result) == {"groundedness"}
    [issue] = result["checks"]["groundedness"]["issues"]
    assert issue["reason"] == "참고문헌 [5]이 본문에서 쓰이지 않음" and issue["line_id"] is None


def test_reference_used_only_in_table_counts_as_used():
    sections = make_sections()
    sections["references"].append(reference(5, "https://epsilon.io/e"))
    chapter(sections, "chapter4")["table"][0]["citation"] = "[5]"
    assert run(sections)["checks"]["groundedness"]["passed"]


# ---------- 편향 (규칙) ----------

def single_domain_evidence():
    evidence = make_evidence()
    evidence[1]["source"] = "https://alpha.com/other"  # www만 다른 같은 도메인
    return evidence


def test_single_domain_without_limit_note_fails_bias():
    result = run(evidence=single_domain_evidence())
    assert failed_checks(result) == {"bias"} and result["passed"] is False
    [issue] = result["checks"]["bias"]["issues"]
    assert issue["company_id"] == "standigm" and issue["line_id"] is None and issue["method"] == "rule"
    assert "단일 출처" in issue["reason"]


@pytest.mark.parametrize("owner, text, passes", [
    pytest.param("standigm", "스탠다임의 근거는 단일 출처에 한정된다.", True, id="기업 note"),
    pytest.param(None, "스탠다임의 근거는 단일 출처에 한정된다.", True, id="기업명만 있는 note"),
    pytest.param("standigm", "스탠다임은 단일출처 의존이다.", True, id="띄어쓰기 다름"),
    pytest.param("diagen", "디어젠의 근거는 단일 출처에 한정된다.", False, id="다른 기업 note"),
])
def test_single_source_limit_note_in_chapter5(owner, text, passes):
    sections = make_sections()
    chapter(sections, "chapter5")["lines"].append(line("ch5-002", text, kind="note", company_id=owner))
    result = run(sections, evidence=single_domain_evidence())
    assert result["checks"]["bias"]["passed"] is passes


def test_single_source_note_outside_chapter5_does_not_count():
    sections = make_sections()
    chapter(sections, "chapter3")["lines"].append(
        line("ch3-002", "스탠다임은 단일 출처다.", kind="note", company_id="standigm"))
    assert run(sections, evidence=single_domain_evidence())["checks"]["bias"]["passed"] is False


def test_single_domain_needs_two_fact_lines():
    sections = make_sections()
    chapter(sections, "chapter2")["lines"].clear()  # 디어젠 사실 1건만 남긴다
    sections["references"].pop()                    # 쓰이지 않게 된 [4]
    result = run(sections)
    assert result["checks"]["bias"]["passed"] and result["passed"]


def test_negative_item_must_be_mentioned_in_its_company_lines():
    scores = {"standigm": make_scores(funding=-2), "diagen": make_scores()}
    result = run(scores_by_company=scores)
    assert failed_checks(result) == {"bias"}
    [issue] = result["checks"]["bias"]["issues"]
    assert issue["company_id"] == "standigm" and "자금 조달" in issue["reason"]

    sections = make_sections()
    chapter(sections, "chapter5")["lines"].append(
        line("ch5-002", "스탠다임: 자금 조달 −2점", kind="note", company_id="standigm"))
    assert run(sections, scores_by_company=scores)["checks"]["bias"]["passed"]

    other = make_sections()  # 다른 기업 라인의 언급은 인정하지 않는다
    chapter(other, "chapter5")["lines"].append(
        line("ch5-002", "디어젠: 자금 조달 −2점", kind="note", company_id="diagen"))
    assert run(other, scores_by_company=scores)["checks"]["bias"]["passed"] is False


@pytest.mark.parametrize("text", ["스탠다임: 법률·정책 관문 미충족", "스탠다임: 법률 · 정책 관문 미충족"])
def test_unmet_gate_must_be_mentioned(text):
    evaluations = make_evaluations()
    evaluations[0]["gates"]["regulation"].update(status="기업 주장만", ok=False)
    scores = {"standigm": make_scores(), "diagen": make_scores()}
    result = run(evaluations=evaluations, scores_by_company=scores)
    [issue] = result["checks"]["bias"]["issues"]
    assert issue["company_id"] == "standigm" and "법률·정책" in issue["reason"]

    sections = make_sections()
    chapter(sections, "chapter4")["lines"].append(line("ch4-002", text, kind="note", company_id="standigm"))
    assert run(sections, evaluations=evaluations, scores_by_company=scores)["checks"]["bias"]["passed"]


def test_item_mention_check_needs_scores_by_company():
    evaluations = make_evaluations()
    evaluations[0]["gates"]["technology"].update(ok=False)
    assert run(evaluations=evaluations)["checks"]["bias"]["passed"]
    assert run(evaluations=evaluations, scores_by_company={})["checks"]["bias"]["passed"]


def test_claim_only_evidence_needs_chapter5_note():
    evidence = make_evidence()
    evidence[0]["status"] = "기업 주장만"
    result = run(evidence=evidence)
    # 이 문장은 귀속 표기가 없어 중립성 규칙에도 걸린다. 여기서 보는 것은 편향(5장 공개) 쪽
    assert "bias" in failed_checks(result)
    [issue] = result["checks"]["bias"]["issues"]
    assert issue["company_id"] == "standigm" and "기업 주장만" in issue["reason"]

    sections = make_sections()
    chapter(sections, "chapter5")["lines"].append(
        line("ch5-002", "스탠다임: 기업 주장만 확인된 항목이 있다.", kind="note", company_id="standigm"))
    assert run(sections, evidence=evidence)["checks"]["bias"]["passed"]


# ---------- 형식 (규칙) ----------

def test_page_limit():
    assert MAX_REPORT_PAGES == 10  # 과제 요구. 정책값이 바뀌면 이 테스트도 같이 검토한다
    assert run(pages=MAX_REPORT_PAGES)["checks"]["format"]["passed"]
    result = run(pages=MAX_REPORT_PAGES + 1)
    assert failed_checks(result) == {"format"} and result["passed"] is False
    assert f"{MAX_REPORT_PAGES + 1}쪽" in result["checks"]["format"]["issues"][0]["reason"]


@pytest.mark.parametrize("phrase", ["이 보고서는", "본 보고서는", "목적으로"])
def test_summary_overview_sentence_fails_format(phrase):
    sections = make_sections()
    sections["summary"].insert(0, line("sum-000", f"{phrase} 투자 위험을 정리한다", kind="note"))
    result = run(sections)
    assert failed_checks(result) == {"format"}
    [issue] = result["checks"]["format"]["issues"]
    assert issue["line_id"] == "sum-000" and phrase in issue["reason"]


def test_overview_phrase_is_allowed_outside_summary():
    sections = make_sections()
    chapter(sections, "chapter5")["lines"].append(line("ch5-002", "이 보고서는 공개 자료만 썼다.", kind="note"))
    assert run(sections)["checks"]["format"]["passed"]


def test_missing_summary_or_references_fails_format():
    sections = make_sections()
    sections["summary"] = []
    assert any("SUMMARY" in i["reason"] for i in run(sections)["checks"]["format"]["issues"])
    sections = make_sections()
    sections["references"] = []
    assert any("참고문헌" in i["reason"] for i in run(sections)["checks"]["format"]["issues"])


# ---------- LLM Judge: 근거성 · 중립성 ----------

def test_non_neutral_fact_line_is_flagged():
    result = run(judge=make_judge(not_neutral={"ch2-001"}))
    assert failed_checks(result) == {"neutrality"} and result["passed"] is False
    assert result["flagged_lines"] == [{"line_id": "ch2-001", "check": "neutrality",
                                        "reason": "ch2-001 판정", "suggestion": "고칠 방향"}]
    [issue] = result["checks"]["neutrality"]["issues"]
    assert (issue["line_id"], issue["company_id"], issue["method"]) == ("ch2-001", "diagen", "llm")
    assert result["summary"] == "중립성 1건 미달"


def test_unsupported_fact_line_is_flagged_for_groundedness():
    result = run(judge=make_judge(unsupported={"ch1-002"}))
    assert failed_checks(result) == {"groundedness"}
    assert [(f["line_id"], f["check"]) for f in result["flagged_lines"]] == [("ch1-002", "groundedness")]
    assert result["summary"] == "근거성 1건 미달"


def test_line_failing_both_checks_is_flagged_twice():
    result = run(judge=make_judge(unsupported={"ch1-002"}, not_neutral={"ch1-002"}))
    assert [(f["line_id"], f["check"]) for f in result["flagged_lines"]] == [
        ("ch1-002", "groundedness"), ("ch1-002", "neutrality")]
    assert result["summary"] == "근거성 1건 · 중립성 1건 미달"


def test_note_line_neutrality_is_reference_only():
    result = run(judge=make_judge(not_neutral={"sum-001", "ch4-001"}))
    neutrality = result["checks"]["neutrality"]
    assert neutrality["passed"] is True and result["passed"] is True
    assert [i["line_id"] for i in neutrality["issues"]] == ["sum-001", "ch4-001"]  # issue로는 남긴다
    assert result["flagged_lines"] == []  # 코드가 만든 문장이라 재작성 대상이 아니다
    assert "참고" in result["summary"] and "2건" in result["summary"]


def test_summary_lists_failures_and_reference_note():
    result = run(judge=make_judge(not_neutral={"ch2-001", "sum-002"}))
    assert result["summary"] == "중립성 1건 미달 · 참고: 요약·4장 코드 문장 중립성 의견 1건"


def test_judge_may_return_plain_dict():
    def judge(items):
        return {"judgments": [
            {"line_id": item["line_id"], "reason": "r", "neutral": True, "suggestion": "",
             "supported": None if item["kind"] == "note" else True} for item in items]}
    assert run(judge=judge)["passed"] is True


# ---------- LLM 실패 ----------

def test_judge_exception_fails_llm_checks_without_raising():
    def boom(items):
        raise RuntimeError("rate limit")

    result = run(judge=boom)  # 예외가 밖으로 나오지 않는다
    assert failed_checks(result) == {"groundedness", "neutrality"} and result["passed"] is False
    for name in ("groundedness", "neutrality"):
        [issue] = result["checks"][name]["issues"]
        assert issue["method"] == "llm" and issue["line_id"] is None
        assert issue["reason"].startswith("LLM 평가 실패") and "rate limit" in issue["reason"]
    assert result["flagged_lines"] == []
    assert result["checks"]["bias"]["passed"] and result["checks"]["format"]["passed"]


def partial_judgments(items):
    return QualityJudgeOutput(judgments=[
        LineJudgment(line_id=items[0]["line_id"], reason="r", supported=None, neutral=True, suggestion="")])


def null_supported(items):
    return QualityJudgeOutput(judgments=[
        LineJudgment(line_id=item["line_id"], reason="r", supported=None, neutral=True, suggestion="")
        for item in items])


@pytest.mark.parametrize("judge", [
    pytest.param(partial_judgments, id="일부 문장 판정 누락"),
    pytest.param(null_supported, id="fact 문장의 supported가 null"),
    pytest.param(lambda items: {"judgments": "없음"}, id="형식이 틀린 출력"),
    pytest.param(lambda items: None, id="빈 응답"),
])
def test_incomplete_judge_output_fails_llm_checks(judge):
    result = run(judge=judge)
    assert failed_checks(result) == {"groundedness", "neutrality"}
    assert result["checks"]["neutrality"]["issues"][0]["reason"].startswith("LLM 평가 실패")


# ---------- 문장이 많을 때 ----------

def many_lines_sections():
    sections = make_sections()
    lines = chapter(sections, "chapter1")["lines"]
    for n in range(MAX_LINES_PER_CALL // 2):
        lines.append(line(f"x-s{n:03d}", "스탠다임 사실. [1]", company_id="standigm",
                          evidence_ids=["standigm-1"], citations=[1]))
        lines.append(line(f"x-d{n:03d}", "디어젠 사실. [3]", company_id="diagen",
                          evidence_ids=["diagen-1"], citations=[3]))
    return sections


def test_many_lines_are_judged_per_company():
    sections, calls = many_lines_sections(), []
    result = run(sections, judge=make_judge(not_neutral={"x-d005"}, calls=calls))
    assert len(calls) == 3  # 스탠다임 · 디어젠 · 기업이 없는 문장
    for batch in calls:
        assert len({find(sections, item["line_id"]).get("company_id") for item in batch}) == 1
    # 보낸 문장은 fact 전체 + SUMMARY · 4장 note이고, 어느 것도 두 번 보내지 않는다
    judged = sorted(item["line_id"] for batch in calls for item in batch)
    expected = sorted(item["id"] for part in (sections["summary"], chapter(sections, "chapter1")["lines"],
                                              chapter(sections, "chapter2")["lines"],
                                              chapter(sections, "chapter4")["lines"]) for item in part)
    assert judged == expected and len(judged) > MAX_LINES_PER_CALL
    assert [f["line_id"] for f in result["flagged_lines"]] == ["x-d005"]


def test_failed_batch_marks_only_its_company():
    sections, ok = many_lines_sections(), make_judge()

    def judge(items):
        if find(sections, items[0]["line_id"]).get("company_id") == "diagen":
            raise RuntimeError("timeout")
        return ok(items)

    result = run(sections, judge=judge)
    issues = result["checks"]["neutrality"]["issues"]
    assert [i["company_id"] for i in issues] == ["diagen"]
    assert issues[0]["reason"].startswith("LLM 평가 실패") and result["passed"] is False


# ---------- 노드 · 기본 Judge ----------

def make_state(**overrides):
    state = {"report_sections": make_sections(), "evidence": make_evidence(),
             "evaluations": make_evaluations(), "report_pages": 8,
             "scores_by_company": {company_id: make_scores() for company_id in NAMES}}
    state.update(overrides)
    return state


def test_quality_node_reads_state_and_returns_quality_only():
    update = quality_node(make_state(), judge=make_judge())
    assert set(update) == {"quality"} and update["quality"]["passed"] is True


def test_quality_node_uses_report_pages_and_scores_from_state():
    state = make_state(report_pages=MAX_REPORT_PAGES + 1)
    format_check = quality_node(state, judge=make_judge())["quality"]["checks"]["format"]
    assert format_check["passed"] is False
    scores = {"standigm": make_scores(funding=-2), "diagen": make_scores()}
    bias = quality_node(make_state(scores_by_company=scores), judge=make_judge())["quality"]["checks"]["bias"]
    assert bias["passed"] is False


def test_quality_node_requires_report_sections():
    with pytest.raises(ValueError, match="report_sections"):
        quality_node({"evidence": []}, judge=make_judge())


def test_quality_node_tolerates_missing_optional_keys():
    update = quality_node({"report_sections": make_sections()}, judge=make_judge())
    assert update["quality"]["passed"] is False  # evidence가 없으니 근거 id를 찾지 못한다


def test_evaluate_uses_llm_judge_by_default(monkeypatch):
    calls = []
    monkeypatch.setattr("quality.evaluator.llm_judge", make_judge(calls=calls))
    result = evaluate(make_sections(), make_evidence(), make_evaluations(), 8)
    assert calls and result["passed"] is True


def test_llm_judge_calls_quality_model_with_structured_output(monkeypatch):
    seen = {}

    class FakeModel:
        def with_structured_output(self, schema):
            seen["schema"] = schema
            return self

        def invoke(self, messages):
            seen["messages"] = messages
            return QualityJudgeOutput(judgments=[])

    def fake_init(model, **kwargs):
        seen["model"], seen["kwargs"] = model, kwargs
        return FakeModel()

    monkeypatch.setattr("langchain.chat_models.init_chat_model", fake_init)
    monkeypatch.setattr("quality.evaluator.load_dotenv", lambda *args, **kwargs: None)
    monkeypatch.delenv("QUALITY_MODEL", raising=False)
    items = [{"line_id": "ch1-001", "kind": "fact", "company": "스탠다임", "text": "사실. [1]", "evidence": []}]

    assert llm_judge(items) == QualityJudgeOutput(judgments=[])
    assert seen["model"] == "gpt-4.1"
    assert seen["kwargs"] == {"model_provider": JUDGE_PROVIDER, "temperature": 0}
    assert seen["schema"] is QualityJudgeOutput
    system, human = seen["messages"]
    assert system.content == PROMPT_PATH.read_text(encoding="utf-8")
    assert "ch1-001" in human.content and "스탠다임" in human.content

    monkeypatch.setenv("QUALITY_MODEL", "gpt-test")
    llm_judge(items)
    assert seen["model"] == "gpt-test"


def test_prompt_defines_both_judgments():
    prompt = PROMPT_PATH.read_text(encoding="utf-8")
    for word in ("line_id", "supported", "neutral", "투자 권유", "기업 간 우열", "전망", "과장 수식어", "기업 주장"):
        assert word in prompt



@pytest.mark.parametrize("claim", ["글로벌 최고 수준의 기술력을 확보했다.",
                                   "임상 1상에서 우수한 안전성 프로파일을 확보하며 순조롭게 진행 중이다."])
def test_hype_words_are_caught_by_rule_even_if_judge_passes(claim):
    """LLM Judge가 통과시켜도 과장 수식어는 규칙이 잡아 재작성 대상으로 넘긴다."""
    import quality.evaluator as qe

    sections = {
        "title": "t", "revision": 0,
        "summary": [{"id": "sum-001", "kind": "note", "company_id": None, "text": "보류 1곳", "evidence_ids": [], "citations": []}],
        "chapters": [{"key": "chapter1", "title": "1", "lines": [
            {"id": "ch1-001", "kind": "fact", "company_id": "galux",
             "text": f"갤럭스 · 기술: {claim} (기업 주장만) [1]",
             "evidence_ids": ["galux-technology-001"], "citations": [1]},
        ]}, {"key": "chapter5", "title": "5", "lines": [
            {"id": "ch5-001", "kind": "note", "company_id": "galux", "text": "갤럭스: 단일 출처 의존, 기업 주장만 1개",
             "evidence_ids": [], "citations": []},
        ]}],
        "references": [{"number": 1, "source": "https://news.example/a", "page": None, "published": None,
                        "accessed": "2026-10-13", "title": None, "evidence_ids": ["galux-technology-001"]}],
    }
    evidence = [{"id": "galux-technology-001", "company_id": "galux", "item": "technology", "fact": "f",
                 "quote": "글로벌 최고 수준의 기술력", "status": "기업 주장만", "source": "https://news.example/a",
                 "page": None, "published": None, "accessed": "2026-10-13"}]

    def lenient_judge(items):
        return {"judgments": [{"line_id": i["line_id"], "supported": True if i["kind"] == "fact" else None,
                               "neutral": True, "reason": "r", "suggestion": ""} for i in items]}

    result = qe.evaluate(sections, evidence, [{"company_id": "galux", "name": "갤럭스"}], 2, judge=lenient_judge)
    assert not result["checks"]["neutrality"]["passed"]
    assert [f["line_id"] for f in result["flagged_lines"]] == ["ch1-001"]
    assert result["flagged_lines"][0]["check"] == "neutrality"


def test_numbers_missing_from_quote_are_groundedness_issues():
    """인용은 300자까지만 저장된다. 문장의 수치가 인용에 없으면(잘린 뒤쪽에만 있던 수치) 근거성 미달이다."""
    import quality.evaluator as qe

    def fact(line_id, text, evidence_id, n):
        return {"id": line_id, "kind": "fact", "company_id": "diagen", "text": text,
                "evidence_ids": [evidence_id], "citations": [n]}

    sections = {
        "title": "t", "revision": 0,
        "summary": [{"id": "sum-001", "kind": "note", "company_id": None, "text": "보류 1곳", "evidence_ids": [], "citations": []}],
        "chapters": [{"key": "chapter1", "title": "1", "lines": [
            fact("ch1-001", "디어젠 · 기술: fostamatinib가 IC50 <1 μM로 TAM을 억제했다. (확인됨) [1]", "diagen-technology-001", 1),
            fact("ch1-002", "디어젠 · 자금 조달: 2022년 2월 시리즈B로 1,200억 원을 유치했다. (확인됨, 2022-02-24 자료) [2]",
                 "diagen-funding-001", 2),
        ]}, {"key": "chapter5", "title": "5", "lines": [
            {"id": "ch5-001", "kind": "note", "company_id": "diagen", "text": "디어젠: 기업 주장만 0개",
             "evidence_ids": [], "citations": []},
        ]}],
        "references": [
            {"number": 1, "source": "https://pmc.example/a", "page": None, "published": None, "accessed": "2026-10-13",
             "title": None, "evidence_ids": ["diagen-technology-001"]},
            {"number": 2, "source": "https://news.example/b", "page": None, "published": "2022-02-24",
             "accessed": "2026-10-13", "title": None, "evidence_ids": ["diagen-funding-001"]},
        ],
    }
    evidence = [
        {"id": "diagen-technology-001", "company_id": "diagen", "item": "technology", "fact": "f",
         "quote": "fostamatinib was predicted to inhibit TAM family members effectively, and we furt",
         "status": "확인됨", "source": "https://pmc.example/a", "page": None, "published": None, "accessed": "2026-10-13"},
        {"id": "diagen-funding-001", "company_id": "diagen", "item": "funding", "fact": "f",
         "quote": "디어젠은 2022년 2월 시리즈B 투자로 1200억원을 유치했다",
         "status": "확인됨", "source": "https://news.example/b", "page": None, "published": "2022-02-24",
         "accessed": "2026-10-13"},
    ]

    def lenient_judge(items):
        return {"judgments": [{"line_id": i["line_id"], "supported": True if i["kind"] == "fact" else None,
                               "neutral": True, "reason": "r", "suggestion": ""} for i in items]}

    result = qe.evaluate(sections, evidence, [{"company_id": "diagen", "name": "디어젠"}], 2, judge=lenient_judge)
    assert not result["checks"]["groundedness"]["passed"]
    flagged = [f for f in result["flagged_lines"] if f["check"] == "groundedness"]
    assert [f["line_id"] for f in flagged] == ["ch1-001"]          # 상태 표기의 날짜 · 쉼표 금액은 지적하지 않는다
    assert "50" in flagged[0]["reason"]


def test_unchanged_lines_reuse_previous_judgment():
    """직전 판과 글자까지 같은 문장은 LLM에 다시 묻지 않고 그 판정을 쓴다. 고친 문장만 새로 판정한다."""
    calls = []
    first = run(judge=make_judge(not_neutral={"ch1-002"}))
    assert [f["line_id"] for f in first["flagged_lines"]] == ["ch1-002"]

    sections = make_sections()
    line_of_sections = next(l for c in sections["chapters"] for l in c["lines"] if l["id"] == "ch1-002")
    line_of_sections["text"] = "스탠다임은 2024년 시리즈A 투자를 받았다고 밝혔다. [2]"
    # 두 번째 Judge는 바뀌지 않은 ch1-001까지 미달로 볼 만큼 흔들리지만, 그 문장은 묻지 않는다
    second = run(sections=sections, judge=make_judge(unsupported={"ch1-001"}, calls=calls), previous=first)
    asked = [item["line_id"] for batch in calls for item in batch]
    assert asked == ["ch1-002"]
    assert second["passed"]
    assert {j["line_id"] for j in second["judgments"]} == {j["line_id"] for j in first["judgments"]}
