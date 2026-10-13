"""통합 보고서 노드: 4개 기업의 판정과 근거로 보고서 1부를 만들고, 품질 지적을 받은 줄만 고쳐 다시 렌더링한다."""

from __future__ import annotations

import copy
import logging
import os
import re
import shutil
from collections import Counter
from pathlib import Path
from typing import Any, Callable

from dotenv import load_dotenv
from pydantic import BaseModel, Field

from config import (AREAS, CANDIDATES, GATE_ITEMS, ITEMS, JUDGE_MODEL, JUDGE_PROVIDER,
                    SENSITIVITY_THRESHOLDS, VERDICT_THRESHOLD)
from report.pdf import render_report
from report.references import CitationIndex, domain_of
from state import State

LOGGER = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "outputs"
REWRITE_PROMPT = (ROOT / "prompts" / "report_rewrite.md").read_text(encoding="utf-8")
SUMMARY_PROMPT = (ROOT / "prompts" / "report_summary.md").read_text(encoding="utf-8")

TITLE = "AI 신약개발 스타트업 투자 심사 보고서"
CHAPTERS = (
    ("chapter1", "1. 기업 개요와 팀", ("management", "funding", "reputation")),
    ("chapter2", "2. 시장 · 경쟁 리스크", ("sales", "competition", "exit")),
    ("chapter3", "3. 기술 · 규제 리스크",
     ("technology", "stage", "manufacturing", "regulation", "overseas", "litigation")),
)
AREA_NAMES = {"company": "기업", "tech": "기술", "regulation": "규제", "market": "시장"}
CLAIM = "기업 주장만"
REWRITE_BATCH = 10
STATUS_LABEL = re.compile(r"\((?:확인됨|기업 주장만|상충함)[^()]*\)")
STATUS_RANK = {"확인됨": 0, CLAIM: 1, "상충함": 2}
MAX_SUMMARY_SENTENCES = 3
QUOTE_PREVIEW = 150
MARKER = re.compile(r"\[\d+\]")
COMMON_LIMITS = (
    "비상장 기업은 공시와 독립 검증 자료가 제한되어, 자료를 찾지 못한 것을 부정 사실로 단정할 수 없다.",
    "점수는 수집한 근거 전체로 계산했고, 1~3장에는 항목별 대표 근거 1건만 실었다.",
    "LLM이 추출한 사실·분류와 근거 상태는 투자 실행 전에 원문과 다시 대조해야 한다.",
)

# summarize_company(evaluation, evidence) -> 문장 목록 [{"text", "evidence_ids"}]
Summarize = Callable[[dict, list[dict]], Any]
# rewrite(requests) -> [{"line_id", "text"}]. requests 원소: {line_id, company, text, reason, suggestion, quotes}
Rewrite = Callable[[list[dict]], Any]


def _plain(text: Any) -> str:
    # 근거 원문의 각주 표시([1] 등)가 보고서의 인용 번호와 섞이지 않게 지운다.
    return " ".join(MARKER.sub("", str(text or "")).split())


def _marks(numbers: list[int]) -> str:
    return " " + "".join(f"[{n}]" for n in numbers) if numbers else ""


def _get(obj: Any, key: str, default: Any = None) -> Any:
    return obj.get(key, default) if isinstance(obj, dict) else getattr(obj, key, default)


class _Lines:
    """한 구역의 줄을 모으며 'ch1-001' 같은 id를 순서대로 붙인다."""

    def __init__(self, prefix: str):
        self.prefix = prefix
        self.items: list[dict[str, Any]] = []
        self._count = 0

    def add(self, kind: str, text: str, company_id: str | None = None, *,
            evidence_ids: list[str] | None = None, citations: list[int] | None = None,
            line_id: str | None = None) -> None:
        if line_id is None:
            self._count += 1
            line_id = f"{self.prefix}-{self._count:03d}"
        self.items.append({"id": line_id, "kind": kind, "company_id": company_id, "text": text,
                           "evidence_ids": evidence_ids or [], "citations": citations or []})


# ---------- judge 결과를 문장으로 ----------

def _humanize_areas(value: str) -> str:
    for code, name in AREA_NAMES.items():
        value = value.replace(f"영역 {code}", f"영역 {name}")
    return value


def _gaps(evaluation: dict) -> tuple[list[str], list[str], bool]:
    gates = [g["name"] for g in evaluation.get("gates", {}).values() if not g.get("ok")]
    areas = [AREA_NAMES.get(a, a) for a, v in evaluation.get("areas", {}).items() if not v.get("confirmed")]
    return gates, areas, evaluation["total"] < VERDICT_THRESHOLD


def _reasons(evaluation: dict) -> list[str]:
    if evaluation["verdict"] == "적격":
        return [f"관문·영역 조건과 합계 기준(+{VERDICT_THRESHOLD}점) 충족"]
    if evaluation["verdict"] == "보류":
        gates, areas, short = _gaps(evaluation)
        reasons = []
        if gates:
            reasons.append(f"관문 {', '.join(gates)} 확인 근거 부족")
        if areas:
            reasons.append(f"{', '.join(areas)} 영역 확인 근거 부족")
        if short:
            reasons.append(f"합계 +{VERDICT_THRESHOLD}점 미달(현재 {evaluation['total']:+d}점)")
        if reasons:
            return reasons
    return [_humanize_areas(r) for r in evaluation.get("reasons", [])] or ["기록 없음"]


def _conditions(evaluation: dict) -> list[str]:
    if evaluation["verdict"] != "보류":
        return []
    gates, areas, short = _gaps(evaluation)
    conditions = []
    if gates:
        conditions.append(f"{', '.join(gates)} 관문을 독립 자료로 +1 이상 확인")
    if areas:
        conditions.append(f"{', '.join(areas)} 영역의 확인됨 근거 확보")
    if short:
        conditions.append(f"합계 +{VERDICT_THRESHOLD}점 이상 확보")
    return conditions or [_humanize_areas(r) for r in evaluation.get("reconsider", [])]


def _core_reason(evaluation: dict) -> str:
    reasons = _reasons(evaluation)
    return reasons[0] if len(reasons) == 1 else f"{reasons[0]} 외 {len(reasons) - 1}건"


def _headline(names: list[str], ordered: list[dict]) -> str:
    counts = Counter(e["verdict"] for e in ordered)
    qualified = [name for name, e in zip(names, ordered) if e["verdict"] == "적격"]
    listed = f"({', '.join(qualified)})" if qualified else ""
    return (f"적격 {counts['적격']}곳{listed} · 보류 {counts['보류']}곳 · 부적격 {counts['부적격']}곳"
            f" | 평가 {len(ordered)}곳")


def _reconsider_text(names: list[str], ordered: list[dict]) -> str:
    holds = [(name, _gaps(e)) for name, e in zip(names, ordered) if e["verdict"] == "보류"]
    if not holds:
        return "재검토 조건: 해당 없음(보류 기업 없음)."
    gate_names = ", ".join(ITEMS[code][0] for code in GATE_ITEMS)
    needs = []
    if any(gaps[0] for _, gaps in holds):
        needs.append(f"관문({gate_names}) 확인됨 +1 이상")
    if any(gaps[1] for _, gaps in holds):
        needs.append("영역별 확인됨 근거")
    if any(gaps[2] for _, gaps in holds):
        needs.append(f"합계 +{VERDICT_THRESHOLD}점 이상")
    listed = ", ".join(name for name, _ in holds)
    return f"재검토 조건: 보류 기업({listed})은 {', '.join(needs)} 조건을 독립 자료로 충족하면 다시 평가한다."


def _gate_area_text(name: str, evaluation: dict) -> str:
    gates = "; ".join(f"{g['name']} {g['score']:+d}점/{g['status']}"
                      for g in evaluation.get("gates", {}).values())
    areas = ", ".join(f"{AREA_NAMES.get(a, a)} {'확인' if v['confirmed'] else '미확인'}"
                      for a, v in evaluation.get("areas", {}).items())
    return f"{name} 관문·영역 — 관문: {gates or '기록 없음'}. 영역: {areas or '기록 없음'}."


def _criteria_text() -> str:
    gates = ", ".join(ITEMS[code][0] for code in GATE_ITEMS)
    areas = ", ".join(AREA_NAMES[area] for area in AREAS)
    bound = 2 * len(ITEMS)
    return (f"판정 기준: 합계 +{VERDICT_THRESHOLD}점 이상, 관문({gates}) 각각 확인됨 +1 이상, "
            f"{len(AREAS)}개 영역({areas})마다 확인됨 근거 1건 이상이면 적격이다. "
            f"관문 항목이 확인된 근거로 -2점이면 부적격, 그 밖에는 보류다. "
            f"환산 점수는 합계(-{bound}~+{bound}점)를 0~100점으로 옮긴 값이다.")


def _sensitivity_text(names: list[str], ordered: list[dict]) -> str | None:
    if not any(e.get("sensitivity") for e in ordered):
        return None
    shifted = []
    for name, e in zip(names, ordered):
        for threshold in SENSITIVITY_THRESHOLDS:
            verdict = e.get("sensitivity", {}).get(f"+{threshold}, 영역규칙 적용")
            if verdict and verdict != e["verdict"]:
                shifted.append((name, f"{name}(+{threshold}점: {e['verdict']}→{verdict})"))
    thresholds = "·".join(f"+{t}점" for t in SENSITIVITY_THRESHOLDS)
    if not shifted:
        return (f"민감도: 기준선을 {thresholds}으로 바꿔도 {len(ordered)}곳 모두 판정이 같다"
                "(영역 확인 규칙 적용 기준).")
    rest = len(ordered) - len({name for name, _ in shifted})
    tail = f" 나머지 {rest}곳은 판정이 같다." if rest else ""
    return (f"민감도: 기준선을 {thresholds}으로 바꾸면 {', '.join(text for _, text in shifted)}의 "
            f"판정이 달라진다(영역 확인 규칙 적용 기준).{tail}")


# ---------- 본문 만들기 ----------

# 표의 빈 칸("No Data", "-")만 따온 인용은 어떤 문장도 뒷받침하지 못한다
EMPTY_QUOTE = re.compile(r"^\W*(?:no data|n/?a|none|null|정보\s*없음)?\W*$", re.IGNORECASE)


def _citable(evidence: dict) -> bool:
    return bool(evidence.get("source") and evidence.get("fact") and evidence.get("status") != "찾지 못함"
                and not EMPTY_QUOTE.match(str(evidence.get("quote") or "")))


BLOG_HOSTS = ("blog.naver.com", "tistory.com", "brunch.co.kr", "post.naver.com", "medium.com", "velog.io")


def _is_blog(source: str) -> bool:
    return any(host in domain_of(source) for host in BLOG_HOSTS)


# 경영진 칸은 사람(대표 · 창업자 · 임원)을 말하는 근거를 먼저 고른다. 플랫폼 소개가 경영진 칸에 오는 것을 막는다
TOPIC = {"management": re.compile(r"대표|CEO|CTO|CSO|CFO|COO|창업자|공동창업|사장|이사|임원|박사|책임자")}
DIGITS = re.compile(r"\d+(?:[.,]\d+)*")


def _numbers_quoted(evidence: dict) -> bool:
    """사실의 수치가 저장된 인용에 모두 있으면 True. 품질 평가의 수치 규칙과 같은 기준이라,
    이런 근거를 먼저 고르면 보고서 문장이 원문 인용으로 바뀌는 일이 줄어든다."""
    quote = re.sub(r"(?<=\d),(?=\d)", "", str(evidence.get("quote") or ""))
    return all(re.sub(r"(?<=\d),(?=\d)", "", n) in quote for n in DIGITS.findall(str(evidence.get("fact") or "")))


def _pick(code: str, candidates: list[dict], judged_ids: list[str], used_domains: set[str],
          used_facts: set[str]) -> dict | None:
    """judge가 쓴 근거, 확인됨 순으로 고르고 순위가 같으면 이 기업이 아직 안 쓴 도메인을 고른다.
    다른 항목에서 이미 쓴 사실은 다시 쓰지 않고(중복), 개인 블로그는 2·3차 가공이라 뒤로 미룬다."""
    pool = [e for e in candidates if e.get("item") == code and _fact_key(e) not in used_facts]
    if not pool:
        return None
    order = {evidence_id: n for n, evidence_id in enumerate(judged_ids)}
    topic = TOPIC.get(code)
    return min(pool, key=lambda e: (
        bool(topic) and not topic.search(e.get("fact", "")),
        not _numbers_quoted(e),
        e["id"] not in order,
        STATUS_RANK.get(e["status"], 3),
        _is_blog(e["source"]),
        domain_of(e["source"]) in used_domains,
        order.get(e["id"], 0),
    ))


def _fact_key(evidence: dict) -> str:
    return re.sub(r"\W", "", str(evidence.get("fact", "")))[:60]


MARKET_SIZE = re.compile(r"시장\s*규모|시장은|환자\s*수|억\s*달러|조\s*원\s*규모|market size|patients", re.IGNORECASE)
IDEA_ITEMS = ("technology", "competition", "stage")
PLATFORM = re.compile(r"플랫폼|platform", re.IGNORECASE)   # 사업 아이디어 = 무엇으로 신약을 찾는가(플랫폼 설명 우선)
ABSENT = re.compile(r"없다|없음|없으며|확인되지 않")


def _extra_line(lines: "_Lines", line_id: str, label: str, company: dict, evidence: dict | None,
                citations: CitationIndex, missing: str) -> None:
    """보고서 필수 내용(사업 아이디어 · 시장 규모)은 12항목 밖이라 별도 ID로 기업 블록 맨 앞에 넣는다."""
    if evidence is None:
        lines.items.append({"id": line_id, "kind": "note", "company_id": company["company_id"],
                            "text": f"{company['name']} · {label}: {missing}", "evidence_ids": [], "citations": []})
        return
    number = citations.add(evidence)
    dated = f", {evidence['published']} 자료" if evidence.get("published") else ""
    lines.items.append({"id": line_id, "kind": "fact", "company_id": company["company_id"],
                        "text": f"{company['name']} · {label}: {_plain(evidence['fact'])} ({evidence['status']}{dated}) [{number}]",
                        "evidence_ids": [evidence["id"]], "citations": [number]})


def _fact_text(company: str, code: str, evidence: dict, number: int) -> str:
    # 기업 주장만인 근거도 언론 보도일 수 있어 "기업 발표"로 단정하지 않고 끝의 상태 표기로 구분한다
    # "내년" 같은 표현의 기준 시점을 알 수 있게 원문 발행일을 함께 적는다
    dated = f", {evidence['published']} 자료" if evidence.get("published") else ""
    return f"{company} · {ITEMS[code][0]}: {_plain(evidence['fact'])} ({evidence['status']}{dated}) [{number}]"


def _item_chapters(candidates: list[dict], evidence_by_company: dict[str, list[dict]],
                   scores: dict, citations: CitationIndex) -> list[dict]:
    domains: dict[str, set[str]] = {c["company_id"]: set() for c in candidates}
    facts: dict[str, set[str]] = {c["company_id"]: set() for c in candidates}
    chapters = []
    for number, (key, title, codes) in enumerate(CHAPTERS, start=1):
        lines = _Lines(f"ch{number}")
        for company in candidates:
            company_id, name = company["company_id"], company["name"]
            pool = evidence_by_company[company_id]
            if key == "chapter1":
                ideas = [e for e in pool if e.get("item") in IDEA_ITEMS and _fact_key(e) not in facts[company_id]]
                idea = min(ideas, key=lambda e: (not PLATFORM.search(e.get("fact", "")), not _numbers_quoted(e),
                                                 IDEA_ITEMS.index(e["item"]), STATUS_RANK.get(e["status"], 3),
                                                 _is_blog(e["source"])), default=None)
                if idea:
                    facts[company_id].add(_fact_key(idea))
                _extra_line(lines, f"ch1-idea-{company_id}", "사업 아이디어", company, idea, citations,
                            "핵심 기술 · 플랫폼을 설명하는 원문 근거를 찾지 못함.")
            if key == "chapter2":
                # "시장 규모 정보가 없다"처럼 부재를 말하거나 수치가 없는 문장은 시장 규모 근거가 아니다
                size = next((e for e in pool if MARKET_SIZE.search(e.get("fact", "")) and re.search(r"\d", e.get("fact", ""))
                             and not ABSENT.search(e.get("fact", "")) and _fact_key(e) not in facts[company_id]), None)
                if size:
                    facts[company_id].add(_fact_key(size))
                _extra_line(lines, f"ch2-size-{company_id}", "시장 규모", company, size, citations,
                            "원문으로 검증한 시장 규모 · 환자 수 수치를 찾지 못함.")
            absent = []
            for code in codes:
                judged = scores.get(company_id, {}).get(code, {}).get("evidence_ids", [])
                item = _pick(code, evidence_by_company[company_id], judged, domains[company_id], facts[company_id])
                if item is None:
                    absent.append(ITEMS[code][0])
                    continue
                domains[company_id].add(domain_of(item["source"]))
                facts[company_id].add(_fact_key(item))
                cited = citations.add(item)
                lines.add("fact", _fact_text(name, code, item, cited), company_id,
                          evidence_ids=[item["id"]], citations=[cited])
            if absent:
                lines.add("note", f"{name} · {', '.join(absent)}: 원문 근거를 찾지 못함.", company_id)
        chapters.append({"key": key, "title": title, "lines": lines.items})
    return chapters


def _sentences(raw: Any) -> list[tuple[Any, Any]]:
    """LLM 출력이 pydantic 객체 · dict · 목록 어느 모양이어도 (text, evidence_ids) 쌍으로 바꾼다."""
    items = raw if isinstance(raw, (list, tuple)) else _get(raw, "sentences")
    return [(_get(item, "text"), _get(item, "evidence_ids")) for item in items or []]


def _company_summary(evaluation: dict, evidence: list[dict], name: str, citations: CitationIndex,
                     summarize_company: Summarize | None) -> list[dict]:
    """LLM이 쓴 판단 요지를 검증해 fact 줄로 만든다. 호출이 실패하면 이 기업은 요지를 생략한다."""
    if not evidence:
        return []
    try:
        raw = (summarize_company or _llm_summarize)(evaluation, evidence)
    except Exception as exc:  # LLM · 네트워크 오류 때문에 그래프가 멈추면 안 된다
        LOGGER.warning("%s 판단 요지를 만들지 못해 생략한다: %s", name, exc)
        return []
    known = {e["id"]: e for e in evidence}
    company_id = evaluation["company_id"]
    lines = _Lines("ch4")
    for text, ids in _sentences(raw):
        text = _plain(text)
        valid = isinstance(ids, (list, tuple)) and ids and all(isinstance(i, str) and i in known for i in ids)
        if not text or not valid:
            LOGGER.warning("%s 판단 요지 문장을 버린다(빈 문장이거나 근거 id가 없거나 목록 밖): %r", name, text[:40])
            continue
        ids = list(dict.fromkeys(ids))
        numbers = list(dict.fromkeys(citations.add(known[i]) for i in ids))
        if name not in text:
            text = f"{name}: {text}"
        lines.add("fact", text + _marks(numbers), company_id, evidence_ids=ids, citations=numbers,
                  line_id=f"ch4-sum-{company_id}-{len(lines.items) + 1}")
        if len(lines.items) == MAX_SUMMARY_SENTENCES:
            break
    return lines.items


def _chapter4(candidates: list[dict], ordered: list[dict], evidence_by_company: dict[str, list[dict]],
              citations: CitationIndex, summarize_company: Summarize | None) -> dict:
    names = [c["name"] for c in candidates]
    lines = _Lines("ch4")
    for company, evaluation in zip(candidates, ordered):
        company_id, name = company["company_id"], company["name"]
        lines.items += _company_summary(evaluation, evidence_by_company[company_id], name,
                                        citations, summarize_company)
        lines.add("note", _gate_area_text(name, evaluation), company_id)
        lines.add("note", f"{name} 판정 사유: {'; '.join(_reasons(evaluation))}.", company_id)
        lines.add("note", f"{name} 재검토 조건: {'; '.join(_conditions(evaluation)) or '해당 없음'}.", company_id)
    lines.add("note", _criteria_text())
    sensitivity = _sensitivity_text(names, ordered)
    if sensitivity:
        lines.add("note", sensitivity)
    table = [{"item": c["name"], "score": e["total"], "status": e["verdict"],
              "citation": f"{e['score100']}/100"} for c, e in zip(candidates, ordered)]
    return {"key": "chapter4", "title": "4. 리스크 종합과 투자 판단", "table": table, "lines": lines.items}


def _cited_domains(chapters: list[dict], evidence_by_id: dict[str, dict]) -> dict[str, set[str]]:
    domains: dict[str, set[str]] = {}
    for chapter in chapters:
        for line in chapter["lines"]:
            if line["kind"] == "fact" and line["company_id"]:
                found = domains.setdefault(line["company_id"], set())
                found.update(domain_of(evidence_by_id[i]["source"]) for i in line["evidence_ids"])
    return domains


def _limit_list(limits: list[dict], status: str) -> str:
    names = [limit["name"] for limit in limits if limit["status"] == status]
    return f"{status} {len(names)}개" + (f"({', '.join(names)})" if names else "")


def _chapter5(candidates: list[dict], ordered: list[dict], scores: dict, chapters: list[dict],
              evidence_by_id: dict[str, dict]) -> dict:
    cited = _cited_domains(chapters, evidence_by_id)
    lines = _Lines("ch5")
    for company, evaluation in zip(candidates, ordered):
        company_id, name = company["company_id"], company["name"]
        limits = evaluation.get("limits", [])
        lines.add("note", f"{name}: " + ", ".join(
            _limit_list(limits, status) for status in ("찾지 못함", "상충함", CLAIM)) + ".", company_id)

        if company_id in scores:
            negative = [(ITEMS[code][0], s["score"]) for code, s in scores[company_id].items()
                        if code in ITEMS and s.get("score", 0) < 0]
        else:
            negative = [(g["name"], g["score"]) for g in evaluation.get("gates", {}).values() if g["score"] < 0]
        if negative:
            lines.add("note", f"{name}: 음수 점수 항목(우려 신호) — "
                      + ", ".join(f"{item} {score:+d}점" for item, score in negative) + ".", company_id)

        domains = cited.get(company_id, set())
        if len(domains) == 1:
            lines.add("note", f"{name}: 본문 인용 출처가 {next(iter(domains))} 1곳뿐이라 단일 출처 의존이다.",
                      company_id)
        elif not domains:
            lines.add("note", f"{name}: 본문에 인용한 출처가 없다.", company_id)
    for text in COMMON_LIMITS:
        lines.add("note", text)
    return {"key": "chapter5", "title": "5. 한계점", "lines": lines.items}


def _summary_lines(candidates: list[dict], ordered: list[dict]) -> list[dict]:
    names = [c["name"] for c in candidates]
    lines = _Lines("sum")
    lines.add("note", _headline(names, ordered))
    for company, evaluation in zip(candidates, ordered):
        lines.add("note", f"{company['name']}: {evaluation['verdict']} {evaluation['total']:+d}점 — "
                  f"{_core_reason(evaluation)} (→ 4장)", company["company_id"])
    lines.add("note", _reconsider_text(names, ordered))
    return lines.items


def build_sections(state: State, summarize_company: Summarize | None = None) -> dict[str, Any]:
    """판정과 상관없이 후보 4곳을 모두 담은 통합 보고서의 문장 구조를 만든다."""
    candidates = state.get("candidates") or CANDIDATES
    evaluations = {e["company_id"]: e for e in state.get("evaluations", [])}  # 같은 기업이 겹치면 뒤쪽이 최신
    absent = [c["name"] for c in candidates if c["company_id"] not in evaluations]
    if absent:
        raise ValueError(f"judge 평가 결과가 없는 기업이 있습니다: {', '.join(absent)}")
    ordered = [evaluations[c["company_id"]] for c in candidates]
    scores = state.get("scores_by_company") or {}
    evidence = state.get("evidence", [])
    evidence_by_id = {e["id"]: e for e in evidence}
    evidence_by_company = {
        c["company_id"]: [e for e in evidence if e.get("company_id") == c["company_id"] and _citable(e)]
        for c in candidates
    }

    citations = CitationIndex()
    chapters = _item_chapters(candidates, evidence_by_company, scores, citations)
    chapters.append(_chapter4(candidates, ordered, evidence_by_company, citations, summarize_company))
    chapters.append(_chapter5(candidates, ordered, scores, chapters, evidence_by_id))
    sections = {
        "title": TITLE,
        "revision": 0,
        "summary": _summary_lines(candidates, ordered),
        "chapters": chapters,
        "references": citations.entries,
    }
    _set_quality_note(sections, "자동 품질 평가: 이 보고서는 생성 뒤 근거성 · 중립성 · 편향 통제 · 형식을 검사받고, "
                                "미달 문장만 최대 2회 고친다. 이 판은 첫 작성본이다.")
    return sections


# ---------- LLM ----------

class SummarySentence(BaseModel):
    text: str = Field(description="판단 요지 한 문장. 인용 번호 [n]은 쓰지 않는다")
    evidence_ids: list[str] = Field(description="문장의 바탕이 된 근거 id. 입력 근거 목록의 id만, 1개 이상")


class CompanySummary(BaseModel):
    sentences: list[SummarySentence] = Field(description="판단 요지 2~3문장")


class LineRewrite(BaseModel):
    line_id: str = Field(description="요청받은 줄 id")
    text: str = Field(description="중립으로 고쳐 쓴 문장")


class RewriteOutput(BaseModel):
    lines: list[LineRewrite] = Field(description="요청받은 줄마다 하나씩")


def _chat_model():
    from langchain.chat_models import init_chat_model

    load_dotenv()
    model = os.getenv("AGENT_MODEL") or JUDGE_MODEL
    provider = os.getenv("AGENT_PROVIDER") or JUDGE_PROVIDER
    return init_chat_model(model, model_provider=provider, temperature=0)


def _summary_prompt(evaluation: dict, evidence: list[dict]) -> str:
    verdict = "\n".join([
        f"판정: {evaluation['verdict']} (합계 {evaluation['total']:+d}점, 환산 {evaluation['score100']}/100)",
        f"판정 사유: {'; '.join(_reasons(evaluation))}",
        f"재검토 조건: {'; '.join(_conditions(evaluation)) or '해당 없음'}",
    ])
    facts = "\n".join(
        f"[{e['id']}] ({e['status']}) {_plain(e['fact'])} / 원문: {_plain(e.get('quote'))[:QUOTE_PREVIEW]}"
        for e in evidence
    )
    return (SUMMARY_PROMPT.replace("{company}", evaluation["name"])
            .replace("{evaluation}", verdict).replace("{evidence}", facts))


def _llm_summarize(evaluation: dict, evidence: list[dict]) -> CompanySummary:
    return _chat_model().with_structured_output(CompanySummary).invoke(_summary_prompt(evaluation, evidence))


def _rewrite_prompt(requests: list[dict]) -> str:
    blocks = [
        f"[{r['line_id']}] 기업: {r['company'] or '(없음)'}\n문장: {r['text']}\n"
        f"지적 사유: {r['reason']}\n수정 제안: {r['suggestion']}\n"
        f"근거 원문: {' | '.join(r['quotes']) or '(없음)'}"
        for r in requests
    ]
    return REWRITE_PROMPT.replace("{lines}", "\n\n".join(blocks))


def _llm_rewrite(requests: list[dict]) -> RewriteOutput:
    return _chat_model().with_structured_output(RewriteOutput).invoke(_rewrite_prompt(requests))


# ---------- 지적받은 줄만 고치기 ----------

def _all_lines(sections: dict) -> list[dict]:
    return list(sections.get("summary", [])) + [line for chapter in sections["chapters"]
                                                for line in chapter["lines"]]


def _reference_number(evidence_id: str, line: dict, references: list[dict]) -> int | None:
    for reference in references:
        if evidence_id in reference.get("evidence_ids", []):
            return reference["number"]
    return (line.get("citations") or [None])[0]


QUOTE_LIMIT = 300   # agents/common.py MAX_QUOTE_CHARS — 근거 인용은 이 길이에서 잘려 저장된다


def _clip(quote: str) -> str:
    """저장 한도에서 잘린 인용은 끊긴 낱말을 버리고 말줄임표를 붙인다(…and we furt → …and we …)."""
    if len(quote) < QUOTE_LIMIT - 5 or quote[-1] in ".!?。\"”'’)":
        return quote
    cut = quote.rfind(" ")
    return (quote[:cut].rstrip(" ,") if cut > 0 else quote) + " …"


def _quote_line(line: dict, evidence_by_id: dict[str, dict], references: list[dict],
                names: dict[str, str]) -> bool:
    """줄을 근거 원문 인용으로 바꾼다. 인용할 원문이나 출처 번호가 없으면 False."""
    company = names.get(line.get("company_id")) or line.get("company_id") or ""
    original = _plain(line.get("text", ""))
    # "스탠다임 · 경영진:" 같은 이름표와 끝의 근거 상태 표기는 그대로 두고 본문만 원문 인용으로 바꾼다
    head = original.split(": ", 1)[0] if " · " in original.split(": ", 1)[0] else company
    status = STATUS_LABEL.search(original)
    for evidence_id in line.get("evidence_ids") or []:
        quote = _plain((evidence_by_id.get(evidence_id) or {}).get("quote"))
        number = _reference_number(evidence_id, line, references)
        if quote and number and not EMPTY_QUOTE.match(quote):
            label = f"{head}: " if head else ""
            tail = f" {status.group(0)}" if status else ""
            line.update(text=f'{label}원문 — "{_clip(quote)}"{tail} [{number}]', evidence_ids=[evidence_id],
                        citations=[number])
            return True
    return False


def _rewrites(raw: Any) -> dict[str, str]:
    if isinstance(raw, dict) and "lines" not in raw:
        return {str(k): v for k, v in raw.items()}
    items = raw if isinstance(raw, (list, tuple)) else _get(raw, "lines")
    return {_get(item, "line_id"): _get(item, "text") for item in items or []}


def _retag(text: str, old: list[int], new: list[int]) -> str:
    tail = re.compile(r"(?:\s*\[\d+\]){%d}\s*$" % len(old))
    return tail.sub("", text) + _marks(new) if tail.search(text) else text


def _prune_references(sections: dict) -> None:
    """본문에서 더 이상 인용하지 않는 출처를 지우고 번호를 1부터 다시 매긴다."""
    lines = _all_lines(sections)
    used = {n for line in lines for n in line.get("citations") or []}
    references = sections.get("references", [])
    kept = [reference for reference in references if reference["number"] in used]
    if len(kept) == len(references):
        return
    renumber = {reference["number"]: new for new, reference in enumerate(kept, start=1)}
    for line in lines:
        old = line.get("citations") or []
        if old:
            new = [renumber.get(n, n) for n in old]
            line["text"] = _retag(line["text"], old, new)
            line["citations"] = new
    for reference in kept:
        reference["number"] = renumber[reference["number"]]
    sections["references"] = kept


def revise_sections(sections: dict, quality: dict, evidence_by_id: dict[str, dict], *,
                    rewrite: Rewrite | None = None, names: dict[str, str] | None = None) -> dict:
    """quality["flagged_lines"]에 오른 줄만 고친다. 나머지 줄은 그대로 둔다.

    근거성: 줄을 근거 원문 인용으로 바꾸고, 인용할 원문이 없으면 줄을 지운다.
    중립성: LLM으로 중립 재작성한다. 같은 줄이 두 지적을 모두 받으면 근거성 처리만 한다.
    names는 company_id -> 기업명이고, 생략하면 config.CANDIDATES를 쓴다.
    """
    revised = copy.deepcopy(sections)
    lines = {line["id"]: line for line in _all_lines(revised)}
    names = names or {c["company_id"]: c["name"] for c in CANDIDATES}
    flagged: dict[str, list[dict]] = {}
    for item in quality.get("flagged_lines") or []:
        flagged.setdefault(item.get("line_id"), []).append(item)
    before = {line_id: lines[line_id]["text"] for line_id in flagged if line_id in lines}

    dropped: set[str] = set()
    requests: list[dict] = []
    for line_id, items in flagged.items():
        line = lines.get(line_id)
        if line is None:
            LOGGER.warning("지적받은 줄 %s이(가) 보고서에 없어 건너뛴다", line_id)
            continue
        checks = {item.get("check") for item in items}
        if "groundedness" in checks and line.get("kind") == "fact":
            if not _quote_line(line, evidence_by_id, revised.get("references", []), names):
                dropped.add(line_id)
        elif "neutrality" in checks:
            neutral = [item for item in items if item.get("check") == "neutrality"]
            quotes = [_plain((evidence_by_id.get(i) or {}).get("quote")) for i in line.get("evidence_ids") or []]
            requests.append({
                "line_id": line_id,
                "company": names.get(line.get("company_id")) or "",
                "text": line["text"],
                "reason": " / ".join(item.get("reason", "") for item in neutral),
                "suggestion": " / ".join(item.get("suggestion", "") for item in neutral),
                "quotes": [quote for quote in quotes if quote],
            })

    if requests:
        try:
            # 한 번에 수십 줄을 보내면 응답이 길이 한도를 넘어 통째로 실패한다 → 10줄씩 나눠 고친다
            replaced = {}
            for start in range(0, len(requests), REWRITE_BATCH):
                replaced.update(_rewrites((rewrite or _llm_rewrite)(requests[start:start + REWRITE_BATCH])))
        except Exception as exc:  # LLM 오류 때문에 이미 만든 보고서까지 잃으면 안 된다
            LOGGER.warning("중립 재작성에 실패해 해당 줄을 그대로 둔다: %s", exc)
            replaced = {}
        for request in requests:
            line = lines[request["line_id"]]
            # LLM이 붙였을 수 있는 [n]은 지우고 원래 인용 번호를 다시 붙인다.
            text = _plain(replaced.get(request["line_id"]))
            if text:
                # 재작성이 끝의 근거 상태 표기(확인됨 · 기업 주장만, 발행일)를 지우면 코드가 다시 붙인다
                label = STATUS_LABEL.search(_plain(request["text"]))
                if label and STATUS_LABEL.search(text):
                    text = STATUS_LABEL.sub(lambda _: label.group(0), text, count=1)
                elif label:
                    text = f"{text.rstrip()} {label.group(0)}"
                line["text"] = text + _marks(line.get("citations") or [])
            else:
                LOGGER.warning("줄 %s의 재작성 결과가 없어 그대로 둔다", request["line_id"])

    if dropped:
        revised["summary"] = [line for line in revised.get("summary", []) if line["id"] not in dropped]
        for chapter in revised["chapters"]:
            chapter["lines"] = [line for line in chapter["lines"] if line["id"] not in dropped]
    _prune_references(revised)
    revised["revision"] = revised.get("revision", 0) + 1
    # 무엇을 왜 고쳤는지 남겨 루프가 실제로 보고서를 바꿨는지 확인할 수 있게 한다
    changes = [{"revision": revised["revision"], "line_id": line_id,
                "check": ", ".join(sorted({item.get("check", "") for item in flagged[line_id]})),
                "reason": " / ".join(item.get("reason", "") for item in flagged[line_id]),
                "before": text, "after": "(삭제)" if line_id in dropped else lines[line_id]["text"]}
               for line_id, text in before.items()]
    revised["changes"] = [*sections.get("changes", []), *changes]
    counts = {check: sum(1 for c in changes if check in c["check"]) for check in ("groundedness", "neutrality")}
    _set_quality_note(revised, f"자동 품질 평가: 직전 판에서 지적된 문장 {len(changes)}건(근거성 {counts['groundedness']}건 · "
                               f"중립성 {counts['neutrality']}건)을 고친 {revised['revision']}차 수정판이다. "
                               "근거성 지적 문장은 원문 인용으로 바꾸고, 중립성 지적 문장은 중립 표현으로 다시 썼다.")
    return revised


QUALITY_NOTE_ID = "ch5-quality"


def _set_quality_note(sections: dict, text: str) -> None:
    """5장 끝의 품질 평가 이력 문장을 넣거나 바꾼다. 코드가 만드는 note라 인용이 없다."""
    lines = sections["chapters"][-1]["lines"]
    for line in lines:
        if line["id"] == QUALITY_NOTE_ID:
            line["text"] = text
            return
    lines.append({"id": QUALITY_NOTE_ID, "kind": "note", "company_id": None, "text": text,
                  "evidence_ids": [], "citations": []})


# ---------- 노드 ----------

def _display_path(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


def report_node(state: State, *, rewrite: Rewrite | None = None,
                summarize_company: Summarize | None = None) -> dict:
    previous, quality = state.get("report_sections"), state.get("quality")
    if previous and quality and not quality.get("passed"):
        # 품질 평가에서 미달이면 처음부터 다시 쓰지 않고 지적받은 줄만 고친다.
        sections = revise_sections(
            previous, quality, {e["id"]: e for e in state.get("evidence", [])}, rewrite=rewrite,
            names={c["company_id"]: c["name"] for c in state.get("candidates") or CANDIDATES},
        )
    else:
        sections = build_sections(state, summarize_company)
    trace_id = re.sub(r"[^\w.-]", "_", str(state.get("trace_id") or "local"))
    path = OUTPUT_DIR / f"{trace_id}_report.pdf"
    # 재작성 전후를 비교할 수 있게 판마다 사본을 남기고, report_path는 항상 최신 판을 가리킨다
    version = path.with_name(f"{trace_id}_report_v{sections['revision']}.pdf")
    try:
        pages = render_report(sections, version)
    except ValueError as exc:
        # 10쪽을 넘어도 그래프를 멈추지 않는다. 그대로 저장하고 품질 평가의 형식 규칙이 미달로 잡게 둔다
        LOGGER.warning("%s", exc)
        pages = render_report(sections, version, strict=False)
    shutil.copyfile(version, path)
    return {
        "report_sections": sections,
        "report_path": _display_path(path),
        "report_pages": pages,
        "report_revisions": sections["revision"],
    }
