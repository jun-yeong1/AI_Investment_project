"""보고서 품질 평가 노드 (3안 Hybrid).

규칙 검사는 코드가, 문장별 근거성 · 중립성 판단만 LLM Judge가 하고, 통과 여부는 코드가 정한다.
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Callable, Optional, TypedDict
from urllib.parse import urlsplit

from dotenv import load_dotenv
from pydantic import BaseModel, Field

from config import ITEMS, JUDGE_PROVIDER, MAX_REPORT_PAGES
from judge.scorer import CLAIM_ONLY

LOGGER = logging.getLogger(__name__)

PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "quality.md"
# 보고서를 쓴 모델(JUDGE_MODEL)과 분리해서 자기 글을 자기가 채점하지 않게 한다
DEFAULT_QUALITY_MODEL = "gpt-4.1"

CHECKS = ("groundedness", "neutrality", "bias", "format")
CHECK_LABELS = {"groundedness": "근거성", "neutrality": "중립성", "bias": "편향", "format": "형식"}
MAX_LINES_PER_CALL = 80
OVERVIEW_PHRASES = ("이 보고서는", "본 보고서는", "목적으로")  # SUMMARY는 결론만 쓴다
SINGLE_SOURCE = "단일 출처"
CITATION = re.compile(r"\[(\d+)\]")


class Issue(TypedDict):
    check: str
    line_id: Optional[str]
    company_id: Optional[str]
    reason: str
    method: str                      # "rule" | "llm"


class CheckResult(TypedDict):
    passed: bool
    issues: list[Issue]


class FlaggedLine(TypedDict):
    line_id: str
    check: str                       # "groundedness" | "neutrality"
    reason: str
    suggestion: str


class QualityResult(TypedDict):
    passed: bool
    revision: int
    checks: dict[str, CheckResult]
    flagged_lines: list[FlaggedLine]
    summary: str


class LineJudgment(BaseModel):
    line_id: str = Field(description="판정한 문장의 line_id")
    reason: str = Field(description="판정 이유 한 줄. 판정보다 먼저 쓴다")
    supported: Optional[bool] = Field(
        description="fact 문장: 인용한 근거 quote가 문장 내용을 뒷받침하면 true. note 문장은 null")
    neutral: bool = Field(
        description="투자 권유 · 기업 간 우열 · 전망 · 과장 수식어 · 기업 주장 단정이 없으면 true")
    suggestion: str = Field(description="미달이면 문장을 고칠 방향, 통과면 빈 문자열")


class QualityJudgeOutput(BaseModel):
    judgments: list[LineJudgment] = Field(description="입력 문장마다 하나씩")


# 문장 묶음(list[dict])을 받아 판정을 돌려주는 함수. 테스트에서는 가짜 함수를 주입한다.
Judge = Callable[[list[dict]], QualityJudgeOutput | dict]


# ---------- 공통 도우미 ----------

def _text(line: dict) -> str:
    return line.get("text", "")


def _has(text: str, phrase: str) -> bool:
    # 띄어쓰기가 달라도 같은 말로 본다 ("자금 조달" / "자금조달")
    return "".join(phrase.split()) in "".join(text.split())


def _markers(text: str) -> list[int]:
    return [int(n) for n in CITATION.findall(text)]


def _domain(source: str) -> str:
    try:
        host = urlsplit(source).netloc.lower().removeprefix("www.")
    except ValueError:
        host = ""
    return host or source  # URL이 아닌 문서명은 문서 하나를 출처 하나로 센다


def _issue(check: str, reason: str, *, line: dict | None = None,
           company_id: str | None = None, method: str = "rule") -> Issue:
    if line is not None:
        company_id = line.get("company_id")
    return {"check": check, "line_id": line.get("id") if line is not None else None,
            "company_id": company_id, "reason": reason, "method": method}


def _lines(sections: dict) -> list[tuple[str, dict]]:
    """(구역, 라인) 목록. 구역은 summary 또는 chapter 키."""
    pairs = [("summary", line) for line in sections.get("summary") or []]
    for chapter in sections.get("chapters") or []:
        pairs += [(chapter.get("key", ""), line) for line in chapter.get("lines") or []]
    return pairs


def _is_company_line(line: dict, company_id: str, name: str) -> bool:
    owner = line.get("company_id")
    return owner == company_id or (owner is None and _has(_text(line), name))


def _mentioned(lines: list[dict], company_id: str, name: str, phrase: str) -> bool:
    return any(_is_company_line(line, company_id, name) and _has(_text(line), phrase)
               for line in lines)


# ---------- 규칙 검사 ----------

def _used_numbers(sections: dict, pairs: list[tuple[str, dict]]) -> set[int]:
    texts = [_text(line) for _, line in pairs]
    # 4장 표의 출처 칸에 [n]을 쓰더라도 본문에서 쓴 것으로 센다
    texts += [str(row.get("citation", "")) for chapter in sections.get("chapters") or []
              for row in chapter.get("table") or []]
    return {n for text in texts for n in _markers(text)}


def _groundedness_rules(sections: dict, pairs: list[tuple[str, dict]],
                        evidence_by_id: dict[str, dict]) -> list[Issue]:
    numbers = {ref["number"] for ref in sections.get("references") or []}
    refs = {ref["number"]: ref for ref in sections.get("references") or []}
    issues = []
    for _, line in pairs:
        if line.get("kind") != "fact":
            continue
        ids = line.get("evidence_ids") or []
        marked = set(_markers(_text(line)))
        cited = set(line.get("citations") or [])
        problems = []
        if not ids:
            problems.append("evidence_ids가 비어 있음")
        problems += [f"evidence에 없는 id: {i}" for i in ids if i not in evidence_by_id]
        if not cited:
            problems.append("citations가 비어 있음")
        if marked != cited:
            problems.append(f"본문 인용 {sorted(marked)}와 citations {sorted(cited)}가 다름")
        problems += [f"참고문헌에 없는 번호 [{n}]" for n in sorted(marked | cited) if n not in numbers]
        # 번호가 달려 있어도 그 참고문헌이 이 문장의 근거를 가리켜야 근거성이 성립한다
        for n in sorted(cited & set(refs)):
            ref_ids = set(refs[n].get("evidence_ids") or [])
            sources = {evidence_by_id[i].get("source") for i in ids if i in evidence_by_id}
            if ref_ids and not ref_ids & set(ids) and refs[n].get("source") not in sources:
                problems.append(f"참고문헌 [{n}]이 이 문장의 근거와 다른 출처를 가리킴")
        issues += [_issue("groundedness", problem, line=line) for problem in problems]
    for n in sorted(numbers - _used_numbers(sections, pairs)):
        issues.append(_issue("groundedness", f"참고문헌 [{n}]이 본문에서 쓰이지 않음"))
    return issues


def _bias_rules(pairs: list[tuple[str, dict]], evidence_by_id: dict[str, dict],
                names: dict[str, str], evaluations_by_id: dict[str, dict],
                scores_by_company: dict) -> list[Issue]:
    limits = [line for key, line in pairs if key == "chapter5"]
    judged = [line for key, line in pairs if key in ("chapter4", "chapter5")]
    facts: dict[str, list[dict]] = {}
    for _, line in pairs:
        if line.get("kind") == "fact" and line.get("company_id"):
            facts.setdefault(line["company_id"], []).append(line)

    issues = []
    for company_id, lines in facts.items():
        name = names.get(company_id, company_id)
        cited = [evidence_by_id[i] for line in lines
                 for i in line.get("evidence_ids") or [] if i in evidence_by_id]
        domains = {_domain(e.get("source", "")) for e in cited}
        # B1: 근거가 한 도메인뿐이면 단일 출처라는 한계를 밝혀야 한다
        if len(lines) >= 2 and len(domains) == 1 and not _mentioned(limits, company_id, name, SINGLE_SOURCE):
            issues.append(_issue(
                "bias", f"{name}: 사실 {len(lines)}건이 모두 {next(iter(domains))} 한 곳인데 5장에 '단일 출처' 한계가 없음",
                company_id=company_id))
        # B3: 기업 주장만 있는 근거를 썼으면 한계점에 그 사실을 남겨야 한다
        if any(e.get("status") == CLAIM_ONLY for e in cited) and not _mentioned(limits, company_id, name, CLAIM_ONLY):
            issues.append(_issue(
                "bias", f"{name}: '기업 주장만' 근거를 인용했는데 5장에 '기업 주장만' 한계가 없음",
                company_id=company_id))

    # B2: 불리한 항목(음수 점수 · 관문 미충족)을 빼고 쓰면 확증편향이 된다
    for company_id, scores in scores_by_company.items():
        name = names.get(company_id, company_id)
        required = [ITEMS[code][0] if code in ITEMS else code
                    for code, score in scores.items() if score.get("score", 0) < 0]
        gates = (evaluations_by_id.get(company_id, {}).get("gates") or {}).values()
        required += [gate["name"] for gate in gates if gate.get("name") and not gate.get("ok")]
        for item_name in dict.fromkeys(required):
            if not _mentioned(judged, company_id, name, item_name):
                issues.append(_issue(
                    "bias", f"{name}: 음수 점수 · 관문 미충족 항목 '{item_name}'이 4 · 5장에 언급되지 않음",
                    company_id=company_id))
    return issues


# 근거 원문에 있어도 보고서 문장에는 쓰지 않는 정도 표현. LLM Judge가 "(기업 주장만)" 표기만 보고 통과시키는 경우를 규칙으로 막는다
HYPE = re.compile(r"최고(?!\s*(?:경영|사업|기술|재무|운영|과학|의학|책임|투자|전략|정보))|최초|최상|획기적|압도적|독보적|혁신적|"
                  r"세계적|선도적|유일한|극대화|수백 배|폭발적|탁월한|퀀텀 점프|우수한|뛰어난|순조롭게|순조로운")
QUOTED = "원문 — \""   # 근거 원문을 그대로 인용한 문장(재작성 결과)은 보고서의 표현이 아니라 출처의 말이다


ATTRIBUTED = re.compile(r"\(기업 주장만|밝혔|따르면|설명이다|설명했")


def _neutrality_rules(pairs: list[tuple[str, dict]], evidence_by_id: dict[str, dict]) -> list[Issue]:
    issues = []
    for _, line in pairs:
        if line.get("kind") != "fact":
            continue
        # 기업 주장만인 근거를 쓴 문장은 상태 표기나 귀속 표현이 있어야 한다(LLM은 이 표기를 실행마다 다르게 읽어 코드가 판정)
        claims = [i for i in line.get("evidence_ids") or [] if (evidence_by_id.get(i) or {}).get("status") == "기업 주장만"]
        if claims and QUOTED not in _text(line) and not ATTRIBUTED.search(_text(line)):
            issues.append(_issue("neutrality", "기업 주장만인 근거를 귀속 없이 사실처럼 씀", line=line))
        if QUOTED in _text(line):
            continue
        found = sorted(set(HYPE.findall(_text(line))))
        if found:
            issues.append(_issue("neutrality", f"과장 수식어 {', '.join(found)} 사용", line=line))
    return issues


def _format_rules(sections: dict, report_pages: int) -> list[Issue]:
    issues = []
    if report_pages > MAX_REPORT_PAGES:
        issues.append(_issue("format", f"보고서가 {report_pages}쪽: {MAX_REPORT_PAGES}쪽 이내여야 함"))
    summary = sections.get("summary") or []
    if not summary:
        issues.append(_issue("format", "SUMMARY 라인이 없음"))
    for line in summary:
        phrase = next((p for p in OVERVIEW_PHRASES if p in _text(line)), None)
        if phrase:
            issues.append(_issue("format", f"SUMMARY에 개요 문장 표현 '{phrase}'이 있음", line=line))
    if not sections.get("references"):
        issues.append(_issue("format", "참고문헌이 없음"))
    return issues


# ---------- LLM Judge ----------

def llm_judge(items: list[dict]) -> QualityJudgeOutput:
    """기본 Judge. 문장 묶음 하나를 LLM 한 번으로 판정한다."""
    from langchain.chat_models import init_chat_model
    from langchain_core.messages import HumanMessage, SystemMessage

    load_dotenv()
    model = os.getenv("QUALITY_MODEL") or DEFAULT_QUALITY_MODEL
    llm = init_chat_model(model, model_provider=JUDGE_PROVIDER, temperature=0)
    messages = [
        SystemMessage(content=PROMPT_PATH.read_text(encoding="utf-8")),
        HumanMessage(content="판정할 문장:\n" + json.dumps(items, ensure_ascii=False, indent=1)),
    ]
    return llm.with_structured_output(QualityJudgeOutput).invoke(messages)


def _evidence_view(line: dict, evidence_by_id: dict[str, dict]) -> list[dict]:
    view = []
    for evidence_id in line.get("evidence_ids") or []:
        e = evidence_by_id.get(evidence_id)
        if e:
            view.append({"id": evidence_id, "quote": e.get("quote", ""),
                         "status": e.get("status", ""), "source": e.get("source", "")})
    return view


def _judge_items(pairs: list[tuple[str, dict]], evidence_by_id: dict[str, dict],
                 names: dict[str, str]) -> list[dict]:
    """Judge에 보낼 문장: fact 전체, 그리고 중립성만 볼 SUMMARY · 4장 note."""
    items = []
    for key, line in pairs:
        is_fact = line.get("kind") == "fact"
        if not is_fact and key not in ("summary", "chapter4"):
            continue
        company_id = line.get("company_id")
        items.append({
            "line_id": line["id"], "kind": "fact" if is_fact else "note",
            "company": names.get(company_id, company_id), "text": _text(line),
            "evidence": _evidence_view(line, evidence_by_id) if is_fact else [],
        })
    return items


def _batches(items: list[dict], lines_by_id: dict[str, dict]) -> list[tuple[str | None, list[dict]]]:
    """호출 한 번에 담는 문장 수에 한도를 두고, 넘으면 기업 단위로 나눈다."""
    if len(items) <= MAX_LINES_PER_CALL:
        return [(None, items)] if items else []
    groups: dict[str | None, list[dict]] = {}
    for item in items:
        groups.setdefault(lines_by_id[item["line_id"]].get("company_id"), []).append(item)
    return list(groups.items())


def _judge_batch(judge: Judge, batch: list[dict]) -> dict[str, LineJudgment]:
    raw = judge(batch)
    out = raw if isinstance(raw, QualityJudgeOutput) else QualityJudgeOutput.model_validate(raw)
    ids = {item["line_id"] for item in batch}
    got: dict[str, LineJudgment] = {}
    for judgment in out.judgments:
        if judgment.line_id in ids:
            got.setdefault(judgment.line_id, judgment)
    # 판정이 빠진 문장을 통과로 치면 검증 안 된 문장이 새어 나간다
    missing = [item["line_id"] for item in batch if item["line_id"] not in got
               or (item["kind"] == "fact" and got[item["line_id"]].supported is None)]
    if missing:
        raise ValueError(f"판정이 빠진 문장 {len(missing)}개: {', '.join(missing)}")
    return got


def _run_judge(judge: Judge, batches: list[tuple[str | None, list[dict]]]):
    results: dict[str, LineJudgment] = {}
    failures: list[tuple[str | None, str]] = []
    for company_id, batch in batches:
        try:
            results.update(_judge_batch(judge, batch))
        except Exception as exc:  # LLM · 네트워크 · 출력 형식 오류로 그래프가 멈추면 안 된다
            LOGGER.warning("품질 Judge 호출 실패: %s", exc)
            failures.append((company_id, f"{type(exc).__name__}: {str(exc)[:200]}"))
    return results, failures


def _llm_issues(items: list[dict], results: dict[str, LineJudgment],
                failures: list[tuple[str | None, str]], lines_by_id: dict[str, dict]):
    grounded: list[Issue] = []
    neutral: list[Issue] = []
    flagged: list[FlaggedLine] = []
    # 한 번의 호출이 두 check를 함께 판정하므로 실패하면 둘 다 확인하지 못한 것이다
    for company_id, error in failures:
        for check, bucket in (("groundedness", grounded), ("neutrality", neutral)):
            bucket.append(_issue(check, f"LLM 평가 실패: {error}", company_id=company_id, method="llm"))
    for item in items:
        judgment = results.get(item["line_id"])
        if judgment is None:
            continue
        line = lines_by_id[item["line_id"]]
        is_fact = item["kind"] == "fact"
        if is_fact and judgment.supported is False:
            reason = judgment.reason or "인용한 근거로 확인되지 않음"
            grounded.append(_issue("groundedness", reason, line=line, method="llm"))
            flagged.append({"line_id": line["id"], "check": "groundedness",
                            "reason": reason, "suggestion": judgment.suggestion})
        if not judgment.neutral:
            reason = judgment.reason or "중립적이지 않은 표현"
            neutral.append(_issue("neutrality", reason, line=line, method="llm"))
            if is_fact:  # note는 코드가 만든 문장이라 재작성 대상이 아니다
                flagged.append({"line_id": line["id"], "check": "neutrality",
                                "reason": reason, "suggestion": judgment.suggestion})
    return grounded, neutral, flagged


# ---------- 판정 ----------

def _summary(blocking: dict[str, list[Issue]], advisory: int) -> str:
    failed = [f"{CHECK_LABELS[name]} {len(found)}건" for name, found in blocking.items() if found]
    text = " · ".join(failed) + " 미달" if failed else "4개 항목 모두 통과"
    if advisory:
        text += f" · 참고: 요약·4장 코드 문장 중립성 의견 {advisory}건"
    return text


def evaluate(sections: dict, evidence: list[dict], evaluations: list[dict], report_pages: int,
             *, judge: Judge | None = None, scores_by_company: dict | None = None) -> QualityResult:
    """보고서 하나를 평가한다. LLM 호출 외에는 부작용이 없다.

    judge(items) -> QualityJudgeOutput 또는 같은 모양의 dict. 생략하면 llm_judge를 쓴다.
    items 원소: {line_id, kind, company, text, evidence: [{id, quote, status, source}]}
    """
    pairs = _lines(sections)
    lines_by_id = {line["id"]: line for _, line in pairs}
    note_ids = {line_id for line_id, line in lines_by_id.items() if line.get("kind") != "fact"}
    evidence_by_id = {e["id"]: e for e in evidence}
    evaluations_by_id = {e["company_id"]: e for e in evaluations if e.get("company_id")}
    names = {company_id: e.get("name") or company_id for company_id, e in evaluations_by_id.items()}

    issues: dict[str, list[Issue]] = {name: [] for name in CHECKS}
    issues["groundedness"] += _groundedness_rules(sections, pairs, evidence_by_id)
    issues["bias"] += _bias_rules(pairs, evidence_by_id, names, evaluations_by_id, scores_by_company or {})
    issues["format"] += _format_rules(sections, report_pages)
    issues["neutrality"] += _neutrality_rules(pairs, evidence_by_id)

    items = _judge_items(pairs, evidence_by_id, names)
    results, failures = _run_judge(judge or llm_judge, _batches(items, lines_by_id))
    grounded, neutral, flagged = _llm_issues(items, results, failures, lines_by_id)
    # 규칙으로 잡힌 근거성 위반도 재작성 대상에 넣는다(원문 인용으로 바꾸면 번호 · 근거 연결이 다시 맞춰진다)
    already = {f["line_id"] for f in flagged}
    for issue in issues["neutrality"]:
        line_id = issue.get("line_id")
        if line_id and line_id not in already and lines_by_id.get(line_id, {}).get("kind") == "fact":
            already.add(line_id)
            flagged.append({"line_id": line_id, "check": "neutrality", "reason": issue["reason"],
                            "suggestion": "정도 표현을 빼고 확인할 수 있는 사실만 남긴다"})
    for issue in issues["groundedness"]:
        line_id = issue.get("line_id")
        if line_id and line_id not in already and lines_by_id.get(line_id, {}).get("kind") == "fact":
            already.add(line_id)
            flagged.append({"line_id": line_id, "check": "groundedness", "reason": issue["reason"],
                            "suggestion": "근거 원문 인용으로 바꾼다"})
    issues["groundedness"] += grounded
    issues["neutrality"] += neutral

    # SUMMARY · 4장 note의 중립성 의견은 남기되 통과 판정에서는 뺀다
    blocking = {name: [i for i in found if not (i["check"] == "neutrality" and i["line_id"] in note_ids)]
                for name, found in issues.items()}
    advisory = sum(len(issues[name]) - len(blocking[name]) for name in CHECKS)
    checks = {name: {"passed": not blocking[name], "issues": issues[name]} for name in CHECKS}
    return {
        "passed": all(check["passed"] for check in checks.values()),
        # supervisor가 이 값과 report_sections["revision"]을 비교해 재평가 여부를 정한다. 그대로 돌려준다
        "revision": sections.get("revision"),
        "checks": checks,
        "flagged_lines": flagged,
        "summary": _summary(blocking, advisory),
    }


def quality_node(state: dict, *, judge: Judge | None = None) -> dict:
    """State의 보고서 · 근거 · 판정을 평가한다. 재작성 여부는 supervisor가 quality["passed"]로 정한다."""
    sections = state.get("report_sections")
    if not sections:
        raise ValueError("품질 평가 전에 report_sections가 있어야 합니다")
    result = evaluate(
        sections,
        state.get("evidence", []),
        state.get("evaluations", []),
        state.get("report_pages") or 0,
        judge=judge,
        scores_by_company=state.get("scores_by_company"),
    )
    return {"quality": result}
