"""점수 변환 · 합계 · 판정 · 민감도. LLM 없이 규칙만 (최종 설계서 C, C-2)."""
from itertools import product

from config import AREAS, GATE_ITEMS, ITEMS, SENSITIVITY_THRESHOLDS, VERDICT_THRESHOLD

CONFIRMED, CLAIM_ONLY, NOT_FOUND, CONFLICT = "확인됨", "기업 주장만", "찾지 못함", "상충함"


def to_score(a: dict) -> int:
    """설계서 C절 to_score 그대로."""
    if a["status"] == CONFLICT:
        return 0
    if a["q1_neg"]:
        return -2
    if a["q2_pos"] and a["status"] == CONFIRMED:
        score = 2
    elif a["q2_pos"] or a["q3_partial"]:
        score = 1
    else:
        score = 0
    return score - 1 if a["q4_concern"] else score


def derive_status(evidence_ids: list[str], evidence_by_id: dict) -> str:
    """인용한 근거들의 상태를 항목 상태 하나로 합친다. (설계서에 규칙이 없어 제안한 규칙)
    상충하는 근거가 있으면 상충함 > 확인됨이 하나라도 있으면 확인됨 > 기업 주장만 > 찾지 못함."""
    statuses = {evidence_by_id[i]["status"] for i in evidence_ids if i in evidence_by_id}
    for s in (CONFLICT, CONFIRMED, CLAIM_ONLY):
        if s in statuses:
            return s
    return NOT_FOUND


def score_item(answer: dict, evidence_by_id: dict) -> dict:
    """LLM 답 1개 -> 점수. 설계서 규칙(−2는 확인된 나쁨만, 찾지 못함은 0)을 to_score 앞에서 적용."""
    a = {k: answer[k] for k in ("q1_neg", "q2_pos", "q3_partial", "q4_concern")}
    # 근거 하나는 한 항목에만 점수로 쓴다: 다른 항목으로 분류된 근거는 이 항목에서 뺀다
    ids = [i for i in answer.get("evidence_ids", [])
           if i in evidence_by_id and evidence_by_id[i].get("item") == answer["item"]]
    a["status"] = derive_status(ids, evidence_by_id)
    if a["q1_neg"] and a["status"] != CONFIRMED:
        # 확인되지 않은 −2는 기업 주장만이면 +1(③), 찾지 못함이면 0으로 처리
        a["q1_neg"] = False
        a["q3_partial"] = a["status"] == CLAIM_ONLY
    if a["status"] == NOT_FOUND:
        a.update(q2_pos=False, q3_partial=False, q4_concern=False)
    return {**a, "score": to_score(a),
            "evidence_ids": ids, "reason": answer.get("reason", "")}


def total_score(scores: dict) -> int:
    return sum(s["score"] for s in scores.values())


def to_100(total: int) -> float:
    return round((total + 24) / 48 * 100, 1)


def decide(scores: dict, threshold: int = VERDICT_THRESHOLD, area_rule: bool = True,
           startup_ok: bool = True) -> dict:
    """판정과 이유 · 재검토 조건."""
    total = total_score(scores)
    reasons, reconsider = [], []

    gate_neg = [g for g in GATE_ITEMS if scores[g]["score"] == -2]  # −2는 확인된 근거에서만 나온다
    if not startup_ok or gate_neg:
        if not startup_ok:
            reasons.append("스타트업 조건 위반")
        reasons += [f"관문 항목 {ITEMS[g][0]}이 확인된 근거로 −2" for g in gate_neg]
        return {"verdict": "부적격", "total": total, "score100": to_100(total),
                "reasons": reasons, "reconsider": []}

    for g in GATE_ITEMS:
        if not (scores[g]["status"] == CONFIRMED and scores[g]["score"] >= 1):
            reconsider.append(f"관문 항목 {ITEMS[g][0]}을 확인됨 근거로 +1 이상 확인")
    if area_rule:
        for area in AREAS:
            if not any(scores[c]["status"] == CONFIRMED for c, v in ITEMS.items() if v[1] == area):
                reconsider.append(f"조사 영역 {area}에서 확인됨 근거 확보")
    if total < threshold:
        reconsider.append(f"합계 +{threshold} 이상 필요(현재 {total})")

    verdict = "보류" if reconsider else "적격"
    reasons = reconsider if reconsider else [f"관문 · 영역 조건 충족, 합계 {total}"]
    return {"verdict": verdict, "total": total, "score100": to_100(total),
            "reasons": reasons, "reconsider": reconsider if verdict == "보류" else []}


def sensitivity(scores: dict) -> dict:
    """기준선(+4/+5/+6) x 영역 확인 규칙 적용 전후의 판정."""
    thresholds = sorted({*SENSITIVITY_THRESHOLDS, VERDICT_THRESHOLD})
    return {f"+{t}, 영역규칙 {'적용' if r else '미적용'}": decide(scores, t, r)["verdict"]
            for t, r in product(thresholds, (True, False))}
