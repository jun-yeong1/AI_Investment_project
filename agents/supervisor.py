"""Supervisor: 현재 State의 근거 충분성을 보고 다음 담당(next)과 지시(task)를 정한다.

1. 충분성 계산 (코드) — judge의 판정 규칙(관문 · 영역 확인됨)을 근거 단계로 당겨 온 것
2. 허용 행동 계산 (코드) — 데이터 의존 · 재작업 예산 · 단계 상한
3. 허용 행동이 둘 이상이거나 재작업이면 LLM이 고르고 사유 · 재작업 검색어를 쓴다
4. LLM이 허용 밖을 고르거나 실패하면 코드가 교정한다 (판정은 LLM, 경계는 코드)
"""

from __future__ import annotations

import json
import logging
import re
import os
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel, Field

from config import (AREAS, GATE_ITEMS, ITEMS, JUDGE_PROVIDER, MAX_REPORT_REVISIONS, MAX_REWORK_PER_AREA,
                    MAX_REWORK_PER_COMPANY, MAX_STEPS, SUPERVISOR_MODEL)
from state import State

LOGGER = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = ROOT / "outputs" / "logs"
PROMPT = (ROOT / "prompts" / "supervisor.md").read_text(encoding="utf-8")
CONFIRMED = "확인됨"
FINISH = "FINISH"
AREA_NAMES = {"company": "기업", "tech": "기술·파이프라인", "regulation": "규제", "market": "시장·사업화"}
RISK_WORDS = re.compile(r"중단|반려|지연|소송|분쟁|해지|철회|실패|보류|hold|suspend|terminat|fail|lawsuit|withdraw|reject",
                        re.IGNORECASE)


class Decision(BaseModel):
    next: str = Field(description="허용 행동 목록 중 하나")
    reason: str = Field(description="State의 근거 상태를 들어 고른 이유 한 문장")
    target_items: list[str] = Field(default_factory=list, description="재작업이면 근거가 부족한 항목 코드")
    queries: list[str] = Field(default_factory=list, description="재작업이면 새 검색어 2~3개")


def sufficiency(state: State) -> dict[str, Any]:
    """현재 기업의 근거가 판정에 충분한지 계산한다. 부족하면 어느 영역 · 항목인지 남긴다."""
    company_id = state["company"]["company_id"]
    mine = [e for e in state.get("evidence", []) if e.get("company_id") == company_id]
    counts = {code: {} for code in ITEMS}
    for evidence in mine:
        bucket = counts.setdefault(evidence["item"], {})
        bucket[evidence["status"]] = bucket.get(evidence["status"], 0) + 1

    gaps = []
    for gate in GATE_ITEMS:
        if not counts[gate].get(CONFIRMED):
            gaps.append({"area": ITEMS[gate][1], "item": gate,
                         "reason": f"관문 {ITEMS[gate][0]}에 확인됨 근거 없음"})
    for area in AREAS:
        codes = [code for code, (_, item_area, _) in ITEMS.items() if item_area == area]
        if not any(counts[code].get(CONFIRMED) for code in codes):
            gaps.append({"area": area, "item": None, "reason": f"{AREA_NAMES[area]} 영역에 확인됨 근거 없음"})
    missing = [code for code in ITEMS if not counts[code]]
    confirmed = sum(bucket.get(CONFIRMED, 0) for bucket in counts.values())
    return {"gaps": gaps, "missing_items": missing, "counts": counts, "evidence_total": len(mine),
            "confirmed_total": confirmed}


def _evaluated(state: State) -> set[str]:
    return {e["company_id"] for e in state.get("evaluations", [])}


def allowed_actions(state: State, suff: dict | None) -> tuple[list[str], str]:
    """허용 행동과 그 근거(로그용 한 줄)를 돌려준다. 순서를 정하는 게 아니라 후보를 거른다."""
    candidates = state.get("candidates", [])
    evaluated = _evaluated(state)
    over_limit = state.get("step_count", 0) >= state.get("max_steps", MAX_STEPS)

    hard_limit = state.get("max_steps", MAX_STEPS) + 2 * len(candidates) + 2 * (MAX_REPORT_REVISIONS + 1)
    if state.get("step_count", 0) >= hard_limit:
        # 보고서 · 품질 노드가 계약과 다른 값을 내도 무한히 돌지 않게 하는 마지막 상한
        return [FINISH], "단계 상한 초과 — 강제 종료"
    if candidates and all(c["company_id"] in evaluated for c in candidates):
        sections = state.get("report_sections")
        if not sections:
            return ["report"], "모든 후보 판정 완료"
        quality = state.get("quality")
        if not quality or quality.get("revision") != sections.get("revision"):
            return ["quality"], "새 보고서는 품질 평가부터"
        if quality.get("passed"):
            return [FINISH], "품질 평가 통과"
        if state.get("report_revisions", 0) < MAX_REPORT_REVISIONS and not over_limit:
            return ["report"], f"품질 미달({quality.get('summary', '')}) — 재작성"
        return [FINISH], "재작성 상한 도달 — 미통과 항목을 남기고 종료"

    company = state.get("company")
    if not company or company.get("company_id") in evaluated:
        return ["select"], "다음 후보 평가"

    status = state.get("area_status", {})
    if over_limit:
        return ["judge"], "단계 상한 도달 — 조사를 멈추고 판정"
    pending = [a for a in AREAS if status.get(a, "pending") == "pending"]
    if pending:
        # 규제 · 시장은 기술 조사가 찾은 물질 · 적응증 단위로 검색해야 의미가 있다(데이터 의존)
        ready = [a for a in pending if a in ("company", "tech") or status.get("tech") in ("done", "failed")]
        return ready, f"미조사 영역 {', '.join(AREA_NAMES[a] for a in pending)}"

    rework = state.get("rework_count", {})
    weak = {g["area"] for g in (suff or {}).get("gaps", [])} | {a for a in AREAS if status.get(a) == "failed"}
    retry = [a for a in AREAS if a in weak and rework.get(a, 0) < MAX_REWORK_PER_AREA]
    if sum(rework.values()) >= MAX_REWORK_PER_COMPANY:
        retry = []
    if retry:
        # 근거가 부족하고 재작업 예산이 남았으면 판정으로 넘어가지 않는다(스텝 수가 아니라 근거 기준)
        return retry, "근거 부족 영역 재작업"
    if weak:
        return ["judge"], "재작업 예산 소진 — 부족한 채로 판정"
    return ["judge"], "관문 · 4영역 모두 확인됨 근거 확보"


@lru_cache(maxsize=1)
def _llm():
    from langchain.chat_models import init_chat_model

    model = os.getenv("SUPERVISOR_MODEL") or SUPERVISOR_MODEL
    return init_chat_model(model, model_provider=JUDGE_PROVIDER, temperature=0).with_structured_output(Decision)


def _brief(state: State, suff: dict | None, allowed: list[str], why: str) -> str:
    company = state.get("company") or {}
    lines = [f"현재 기업: {company.get('name', '-')} (영문명 {company.get('en', '-')})",
             f"영역 상태: {json.dumps(state.get('area_status', {}), ensure_ascii=False)}",
             f"재작업 횟수: {json.dumps(state.get('rework_count', {}), ensure_ascii=False)} "
             f"(영역당 {MAX_REWORK_PER_AREA}회, 기업당 {MAX_REWORK_PER_COMPANY}회까지)",
             f"파이프라인: {', '.join(p['substance'] for p in state.get('pipeline', [])) or '없음'}"]
    if suff:
        lines.append(f"현재 기업 근거 {suff['evidence_total']}건, 항목별 상태:")
        for code, bucket in suff["counts"].items():
            gate = ", 관문" if ITEMS[code][2] else ""
            lines.append(f"- {code}({ITEMS[code][0]}, 영역 {ITEMS[code][1]}{gate}): "
                         f"{', '.join(f'{k} {v}' for k, v in bucket.items()) or '근거 없음'}")
        lines.append("부족: " + ("; ".join(g["reason"] for g in suff["gaps"]) or "없음"))
    used = [q for q in state.get("task", {}).get("queries", [])]
    if used:
        lines.append(f"직전 재작업 검색어: {' / '.join(used)}")
    lines.append(f"허용 행동: {', '.join(allowed)} (코드가 거른 이유: {why})")
    return "\n".join(lines)


def choose_with_llm(state: State, suff: dict | None, allowed: list[str], why: str) -> Decision:
    from langchain_core.messages import HumanMessage, SystemMessage

    return _llm().invoke([SystemMessage(content=PROMPT),
                          HumanMessage(content=_brief(state, suff, allowed, why))])


def _fallback_queries(state: State, area: str, suff: dict | None) -> list[str]:
    name = state["company"]["name"]
    items = [g["item"] for g in (suff or {}).get("gaps", []) if g["area"] == area and g["item"]]
    items = items or [code for code, (_, a, _) in ITEMS.items() if a == area]
    names = " ".join(ITEMS[code][0] for code in items)
    return [f"{name} {names} 공시 독립 보도", f"{name} {names} 중단 지연 분쟁"]


def _log(state: State, record: dict) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    path = LOG_DIR / f"{state.get('trace_id', 'local')}.jsonl"
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(record, ensure_ascii=False) + "\n")


def supervisor_node(state: State, *, choose: Callable[..., Decision] | None = None) -> dict:
    company = state.get("company")
    evaluated = _evaluated(state)
    researching = bool(company) and company.get("company_id") not in evaluated
    suff = sufficiency(state) if researching else None
    allowed, why = allowed_actions(state, suff)
    status = state.get("area_status", {})
    rework_candidates = [a for a in allowed if a in AREAS and status.get(a, "pending") != "pending"]

    decision, used_llm, override = None, False, False
    if len(allowed) > 1 or rework_candidates:
        used_llm = True
        try:
            decision = (choose or choose_with_llm)(state, suff, allowed, why)
        except Exception as exc:  # LLM 실패로 그래프가 멈추지 않게 코드 기본값으로 진행한다
            LOGGER.warning("supervisor LLM 실패: %s", exc)
            decision = None
    if decision is None or decision.next not in allowed:
        override = used_llm
        decision = Decision(next=allowed[0], reason=why)

    nxt = decision.next
    mode = "rework" if nxt in AREAS and status.get(nxt, "pending") != "pending" else "initial"
    task = {"area": nxt if nxt in AREAS else None, "mode": mode, "reason": decision.reason,
            "target_items": [], "queries": []}
    if nxt in ("regulation", "market"):
        # 기술 워커의 결과를 supervisor가 받아 다음 워커 지시에 실어 보낸다(워커끼리 직접 주고받지 않음)
        task["pipeline"] = list(state.get("pipeline", []))
    update: dict[str, Any] = {"next": nxt, "task": task}
    if mode == "rework":
        targets = [code for code in decision.target_items if code in ITEMS and ITEMS[code][1] == nxt]
        task["target_items"] = targets or [g["item"] for g in suff["gaps"] if g["area"] == nxt and g["item"]]
        queries = [q for q in decision.queries if q.strip()][:3] or _fallback_queries(state, nxt, suff)
        if not any(RISK_WORDS.search(q) for q in queries):
            # 확증 편향을 막으려고 위험 방향 검색어 하나는 코드가 보장한다(LLM이 빠뜨려도)
            queries = [*queries[:2], _fallback_queries(state, nxt, suff)[-1]]
        task["queries"] = queries
        rework = dict(state.get("rework_count", {}))
        rework[nxt] = rework.get(nxt, 0) + 1
        update["rework_count"] = rework
    if nxt == FINISH:
        quality = state.get("quality") or {}
        update["status"] = "done" if quality.get("passed") else "quality_failed"
    else:
        update["step_count"] = 1

    _log(state, {
        "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
        "trace_id": state.get("trace_id"),
        "step": state.get("step_count", 0),
        "company": (company or {}).get("company_id"),
        "next": nxt,
        "mode": mode,
        "reason": decision.reason,
        "allowed": allowed,
        "filter": why,
        "gaps": [g["reason"] for g in suff["gaps"]] if suff else [],
        # 재작업 전후 비교용: 이 결정 시점의 현재 기업 근거 수 · 확인됨 수
        "evidence": suff["evidence_total"] if suff else None,
        "confirmed": suff["confirmed_total"] if suff else None,
        "queries": task["queries"],
        "llm": used_llm,
        "override": override,
    })
    return update
