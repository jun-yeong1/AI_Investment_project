import pytest

from config import GATE_ITEMS, ITEMS
from judge.node import build_prompt, summarize
from judge.scorer import report_facts, decide, derive_status, sensitivity, to_100, to_score, score_item


def a(status, q1=False, q2=False, q3=False, q4=False):
    return {"status": status, "q1_neg": q1, "q2_pos": q2, "q3_partial": q3, "q4_concern": q4}


# to_score: 분기마다 하나씩
@pytest.mark.parametrize("ans, expected", [
    (a("상충함", q1=True, q2=True), 0),          # 근거 충돌 -> 0
    (a("확인됨", q1=True), -2),                  # 확인된 나쁨
    (a("확인됨", q2=True), 2),                   # 확인된 +2
    (a("기업 주장만", q2=True), 1),              # 기업 주장만이면 +1
    (a("확인됨", q3=True), 1),                   # 일부만
    (a("찾지 못함"), 0),                         # 근거 없음
    (a("확인됨", q2=True, q4=True), 1),          # +2에서 우려 -1
    (a("확인됨", q1=True, q4=True), -2),         # -2는 우려와 상관없이 -2
    (a("찾지 못함", q4=True), -1),               # 우려만 있으면 -1
])
def test_to_score(ans, expected):
    assert to_score(ans) == expected


def ev(id_, status, item="x"):
    return {"id": id_, "status": status, "item": item}


def test_derive_status():
    by_id = {"e1": ev("e1", "확인됨"), "e2": ev("e2", "기업 주장만"), "e3": ev("e3", "상충함")}
    assert derive_status([], by_id) == "찾지 못함"
    assert derive_status(["nope"], by_id) == "찾지 못함"
    assert derive_status(["e2"], by_id) == "기업 주장만"
    assert derive_status(["e1", "e2"], by_id) == "확인됨"
    assert derive_status(["e1", "e3"], by_id) == "상충함"


def test_unverified_negative_is_not_minus2():
    by_id = {"e2": ev("e2", "기업 주장만")}
    ans = {"item": "x", "q1_neg": True, "q2_pos": False, "q3_partial": False, "q4_concern": False,
           "evidence_ids": ["e2"]}
    assert score_item(ans, by_id)["score"] == 1   # 기업 주장만 -> ③ +1로 처리
    assert score_item({**ans, "evidence_ids": []}, by_id)["score"] == 0


def make_scores(default_score=1, status="확인됨", **override):
    scores = {c: {"score": default_score, "status": status} for c in ITEMS}
    for code, (score, st) in override.items():
        scores[code] = {"score": score, "status": st}
    return scores


def test_verdict_qualified():
    r = decide(make_scores(1))            # 합계 +12, 모든 영역 확인됨
    assert r["verdict"] == "적격"
    assert r["score100"] == to_100(12)


def test_verdict_disqualified_by_gate():
    r = decide(make_scores(1, technology=(-2, "확인됨")))
    assert r["verdict"] == "부적격"


def test_hold_when_gate_unconfirmed():
    r = decide(make_scores(1, technology=(1, "기업 주장만")))
    assert r["verdict"] == "보류" and r["reconsider"]


def test_hold_when_area_unconfirmed():
    scores = make_scores(1)
    for c, v in ITEMS.items():
        if v[1] == "market":
            scores[c]["status"] = "기업 주장만"
    assert decide(scores)["verdict"] == "보류"
    assert decide(scores, area_rule=False)["verdict"] == "적격"


def test_hold_when_total_low():
    r = decide(make_scores(0, technology=(1, "확인됨"), regulation=(1, "확인됨")))
    assert r["verdict"] == "보류"


def test_startup_violation():
    assert decide(make_scores(1), startup_ok=False)["verdict"] == "부적격"


def test_sensitivity_keys():
    assert len(sensitivity(make_scores(1))) == 6   # 기준선 3 x 영역규칙 2


def test_summarize_end_to_end():
    company = {"company_id": "x", "name": "테스트"}
    evidence = [{"id": f"x-{c}", "company_id": "x", "item": c, "status": "확인됨",
                 "fact": "사실", "source": "u"} for c in ITEMS]
    answers = [{"item": c, "q1_neg": False, "q2_pos": True, "q3_partial": False,
                "q4_concern": False, "evidence_ids": [f"x-{c}"], "reason": "r"} for c in ITEMS]
    out = summarize(company, answers, evidence)
    assert out["verdict"] == "적격" and out["total"] == 24   # 12항목 모두 +2, 확인됨
    partial = [dict(x, evidence_ids=[]) if x["item"] == "sales" else x for x in answers]
    assert summarize(company, partial, evidence)["scores"]["sales"]["score"] == 0  # 근거 없음 -> 0
    assert out["evaluations"][0]["company_id"] == "x"
    missing = summarize(company, answers[:-1], evidence)   # 빠진 항목은 0점 · 찾지 못함
    assert missing["scores"]["exit"]["status"] == "찾지 못함" and len(missing["scores"]) == 12
    assert "테스트" in build_prompt(company, evidence)


def test_evidence_only_counts_for_its_own_item():
    by_id = {"e1": ev("e1", "확인됨", item="technology")}
    ans = {"item": "regulation", "q1_neg": False, "q2_pos": True, "q3_partial": False,
           "q4_concern": False, "evidence_ids": ["e1"]}
    r = score_item(ans, by_id)                # technology 근거를 regulation에 쓰면 인정 안 됨
    assert r["status"] == "찾지 못함" and r["score"] == 0 and r["evidence_ids"] == []


def test_report_facts():
    scores = make_scores(1, technology=(1, "기업 주장만"), sales=(0, "찾지 못함"))
    for c in scores:
        scores[c]["reason"] = "r"
    f = report_facts(scores)
    assert f["gates"]["technology"]["ok"] is False and f["gates"]["regulation"]["ok"] is True
    assert all(v["confirmed"] for v in f["areas"].values())
    assert {x["item"] for x in f["limits"]} == {"technology", "sales"}
