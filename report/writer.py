"""D-2의 보고서 노드: judge 결과와 실제 근거로 E절의 장을 만든다."""

from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from config import CANDIDATES, ITEMS, VERDICT_THRESHOLD
from report.pdf import render_report
from report.references import CitationIndex
from state import State

OUTPUT_DIR = Path(__file__).resolve().parents[1] / "outputs"
CHAPTER_ITEMS = {
    "chapter1": ("management", "funding", "reputation"),
    "chapter2": ("sales", "competition", "exit"),
    "chapter3": ("technology", "stage", "manufacturing", "regulation", "overseas", "litigation"),
}


def _evaluation(state: State, company_id: str) -> dict:
    for evaluation in reversed(state.get("evaluations", [])):
        if evaluation.get("company_id") == company_id:
            return evaluation
    raise ValueError(f"{company_id}의 judge 평가 결과가 없습니다")


def _evidence_for(state: State, company_id: str) -> dict[str, dict]:
    return {e["id"]: e for e in state.get("evidence", []) if e.get("company_id") == company_id}


def _representative(code: str, scores: dict, evidence: dict[str, dict]) -> dict | None:
    # judge가 실제 사용한 근거를 우선하고, 없으면 조사 결과 한 건만 개요에 쓴다.
    scored_ids = scores.get(code, {}).get("evidence_ids", [])
    for evidence_id in scored_ids:
        item = evidence.get(evidence_id)
        if item and item.get("item") == code:
            return item
    return next((e for e in evidence.values() if e.get("item") == code), None)


def _fact_lines(codes: tuple[str, ...], scores: dict, evidence: dict[str, dict], citations: CitationIndex) -> list[str]:
    lines = []
    for code in codes:
        item = _representative(code, scores, evidence)
        name = ITEMS[code][0]
        if item:
            lines.append(f"{name}: {item['fact']} ({item['status']}) {citations.cite(item)}")
        else:
            lines.append(f"{name}: 기업별 원문 근거를 확보하지 못함.")
    return lines


def _summary(company: dict, evaluation: dict) -> list[str]:
    lines = [
        f"{evaluation['verdict']} | {company['name']} | 합계 {evaluation['total']:+d}점 "
        f"| 환산 {evaluation['score100']}/100점",
    ]
    reasons = list(evaluation.get("reasons", []))[:3]
    supplements = [
        f"관문: {', '.join(g['name'] for g in evaluation.get('gates', {}).values() if g.get('ok')) or '충족 근거 없음'}",
        f"확인된 영역: {', '.join(a for a, v in evaluation.get('areas', {}).items() if v.get('confirmed')) or '없음'}",
        f"합계 기준: +{VERDICT_THRESHOLD}점",
    ]
    for supplement in supplements:
        if len(reasons) >= 3:
            break
        reasons.append(supplement)
    lines.extend(f"판정 이유 {i}. {reason} (→ 4장)" for i, reason in enumerate(reasons, 1))
    reconsider = evaluation.get("reconsider", [])
    lines.append("재검토 조건: " + ("; ".join(reconsider) if reconsider else "현재 판정 기준상 없음"))
    return lines


def build_qualified_sections(state: State) -> dict[str, Any]:
    """본문 1~5장과 인용을 먼저 만든 뒤 마지막에 SUMMARY를 압축한다."""
    company = state["company"]
    company_id = company["company_id"]
    evaluation = _evaluation(state, company_id)
    if state.get("verdict") != "적격" or evaluation.get("verdict") != "적격":
        raise ValueError("적격 기업에만 개별 보고서를 생성합니다")
    scores = state.get("scores", {})
    if set(scores) != set(ITEMS):
        raise ValueError("judge의 12항목 점수가 모두 있어야 합니다")
    evidence = _evidence_for(state, company_id)
    citations = CitationIndex()

    chapter1 = ["사업 아이디어와 경영진·투자 이력을 확인된 원문 범위에서 정리한다."]
    idea = _representative("technology", scores, evidence)
    chapter1.append(
        f"사업 아이디어: {idea['fact']} {citations.cite(idea)}" if idea
        else "사업 아이디어: 기업별 원문 근거를 확보하지 못함."
    )
    chapter1 += _fact_lines(CHAPTER_ITEMS["chapter1"], scores, evidence, citations)

    chapter2 = _fact_lines(CHAPTER_ITEMS["chapter2"], scores, evidence, citations)
    market_size = next(
        (e for e in evidence.values() if e.get("item") in CHAPTER_ITEMS["chapter2"]
         and any(term in e.get("fact", "") for term in ("시장 규모", "환자 수", "시장규모"))),
        None,
    )
    chapter2.insert(0, f"시장 규모·환자 수: {market_size['fact']} {citations.cite(market_size)}"
                    if market_size else "시장 규모·환자 수: 원문으로 검증한 수치 없음.")

    chapter3 = _fact_lines(CHAPTER_ITEMS["chapter3"], scores, evidence, citations)
    pipeline_lines = []
    for item in state.get("pipeline", [])[:5]:
        source = next(
            (e for e in evidence.values() if e.get("item") == "stage" and item["substance"].casefold()
             in (e.get("fact", "") + " " + e.get("quote", "")).casefold()),
            None,
        )
        if source:
            pipeline_lines.append(
                f"{item['substance']} — {item['indication']} / {item['stage']} {citations.cite(source)}"
            )
    chapter3 += ["물질·적응증별 파이프라인:"] + (pipeline_lines or ["출처가 연결된 물질별 목록 없음."])

    rows = []
    for code, (name, _, gate) in ITEMS.items():
        score = scores[code]
        used = next((evidence[i] for i in score.get("evidence_ids", [])
                     if i in evidence and evidence[i].get("item") == code), None)
        rows.append({
            "item": name + (" *" if gate else ""),
            "score": score["score"],
            "status": score["status"],
            "citation": citations.cite(used) if used else "—",
        })
    gates = evaluation.get("gates", {})
    areas = evaluation.get("areas", {})
    chapter4 = {
        "rows": rows,
        "notes": [
            f"판정 기준: 합계 +{VERDICT_THRESHOLD}점 이상, 기술·법률 관문 각각 확인됨 +1 이상, 4영역별 확인됨 근거 필요.",
            "평가표의 출처 표시는 항목별 대표 인용 1건이며, 점수는 judge의 전체 근거 ID로 계산했다.",
            "관문: " + "; ".join(f"{v['name']} {v['score']:+d}점/{v['status']}"
                                   for v in gates.values()),
            "영역: " + "; ".join(f"{area} {'확인' if value['confirmed'] else '미확인'}"
                                   for area, value in areas.items()),
            f"최종 판정: {evaluation['verdict']} ({evaluation['total']:+d}점, "
            f"{evaluation['score100']}/100점).",
        ] + [f"판정 사유: {reason}" for reason in evaluation.get("reasons", [])],
    }

    by_status: dict[str, list[str]] = defaultdict(list)
    for code, score in scores.items():
        if score["status"] != "확인됨":
            by_status[score["status"]].append(ITEMS[code][0])
    chapter5 = [
        f"찾지 못함: {', '.join(by_status['찾지 못함']) or '없음'}.",
        f"상충함: {', '.join(by_status['상충함']) or '없음'}.",
        f"기업 주장만: {', '.join(by_status['기업 주장만']) or '없음'}.",
        "비상장 기업은 공시와 독립 검증 자료가 제한되어 부재 정보를 부정 사실로 단정할 수 없다.",
        "LLM의 원문 추출과 예/아니오 판단에는 분류 오류가 있을 수 있어 원문·인용을 재검토해야 한다.",
    ]

    return {
        "kind": "qualified",
        "title": f"{company['name']} 투자 심사 보고서",
        "company_id": company_id,
        "summary": _summary(company, evaluation),  # 본문 완성 뒤 작성
        "chapter1": chapter1,
        "chapter2": chapter2,
        "chapter3": chapter3,
        "chapter4": chapter4,
        "chapter5": chapter5,
        "references": citations.entries,
    }


def build_no_qualified_sections(state: State) -> dict[str, Any]:
    """적격이 한 곳도 없을 때 4곳 비교와 기업별 이유·재검토 조건을 만든다."""
    candidates = state.get("candidates", CANDIDATES)
    evaluations = {e["company_id"]: e for e in state.get("evaluations", [])}
    if state.get("reports") or any(e.get("verdict") == "적격" for e in evaluations.values()):
        raise ValueError("적격 보고서가 있으면 '적격 없음' 보고서를 만들 수 없습니다")
    if any(c["company_id"] not in evaluations for c in candidates):
        raise ValueError("모든 후보의 judge 평가가 끝나야 합니다")
    ordered = [evaluations[c["company_id"]] for c in candidates]
    missing = Counter(limit["status"] for e in ordered for limit in e.get("limits", []))
    chapter4 = {
        "rows": [{
            "item": e["name"], "score": e["total"], "status": e["verdict"],
            "citation": f"{e['score100']}/100",
        } for e in ordered],
        "notes": [
            f"{e['name']}: 판정 이유 — {'; '.join(e.get('reasons', [])) or '기록 없음'} / "
            f"재검토 조건 — {'; '.join(e.get('reconsider', [])) or '없음'}"
            for e in ordered
        ],
    }
    return {
        "kind": "no_qualified",
        "title": "AI 신약개발 스타트업 투자 심사 — 적격 없음",
        "company_id": None,
        "summary": [
            f"적격 없음 | 평가 후보 {len(candidates)}곳",
            f"판정 이유 1. 기준 +{VERDICT_THRESHOLD}점과 관문·영역 규칙을 모두 충족한 기업 없음 (→ 4장)",
            "판정 이유 2. 기업별 미충족 조건은 4장 비교표에 정리 (→ 4장)",
            "판정 이유 3. 찾지 못한 정보와 기업 주장만인 항목은 5장에서 구분 (→ 5장)",
            "재검토 조건: 각 기업의 4장 조건에 해당하는 독립 원문 근거 확보.",
        ],
        "chapter1": [
            "평가 대상: " + " → ".join(c["name"] for c in candidates),
            "기업별 사업·팀 사실은 개별 조사 근거에 한하며, 이 비교본에는 미검증 사실을 추가하지 않는다.",
        ],
        "chapter2": [
            f"{e['name']}: 시장·사업화 영역 "
            f"{'확인됨 근거 있음' if e.get('areas', {}).get('market', {}).get('confirmed') else '확인됨 근거 부족'}"
            for e in ordered
        ],
        "chapter3": [
            f"{e['name']}: " + "; ".join(
                f"{g['name']} {g['score']:+d}점/{g['status']}"
                for g in e.get("gates", {}).values()
            ) for e in ordered
        ],
        "chapter4": chapter4,
        "chapter5": [
            f"평가 항목 상태 합계: 찾지 못함 {missing['찾지 못함']}건, "
            f"상충함 {missing['상충함']}건, 기업 주장만 {missing['기업 주장만']}건.",
            "비상장 기업은 공개 정보가 제한되어 자료 부재를 부정 사실로 단정할 수 없다.",
            "LLM이 추출한 사실·분류와 근거 상태는 투자 실행 전에 원문과 재대조해야 한다.",
        ],
        "references": [],  # 이 비교본에는 개별 외부 자료의 사실을 직접 인용하지 않는다.
    }


def report_node(state: State) -> dict:
    sections = build_qualified_sections(state)
    index = state.get("current_idx", 0) + 1
    path = OUTPUT_DIR / f"{index:02d}_{sections['company_id']}_report.pdf"
    render_report(sections, path)
    return {"reports": [str(path)], "report_sections": sections,
            "references": sections["references"]}


def no_qualified_node(state: State) -> dict:
    sections = build_no_qualified_sections(state)
    path = OUTPUT_DIR / "no_qualified_report.pdf"
    render_report(sections, path)
    return {"reports": [str(path)], "report_sections": sections,
            "references": sections["references"]}
