"""투자 판단 노드: 현재 기업 근거 -> LLM 예/아니오 답 -> scorer -> State."""
from pathlib import Path

from langchain.chat_models import init_chat_model

from config import JUDGE_MODEL, JUDGE_PROVIDER
from judge.rubric import RUBRIC
from judge.schema import JudgeOutput
from judge.scorer import decide, score_item, sensitivity, total_score

PROMPT = (Path(__file__).parent.parent / "prompts" / "judge.md").read_text(encoding="utf-8")


def _rubric_text() -> str:
    return "\n".join(
        f"- {code} ({r['name']}{' · 관문' if r['gate'] else ''}): "
        f"① {r['neg']} / ② {r['pos']} / ③ {r['partial']}"
        for code, r in RUBRIC.items()
    )


def _evidence_text(evidence: list[dict]) -> str:
    if not evidence:
        return "(근거 없음)"
    return "\n".join(
        f"[{e['id']}] ({e['item']} · {e['status']}) {e['fact']} — {e['source']}" for e in evidence
    )


def build_prompt(company: dict, evidence: list[dict]) -> str:
    return PROMPT.format(rubric=_rubric_text(), company=company["name"],
                         evidence=_evidence_text(evidence))


def summarize(company: dict, answers: list[dict], evidence: list[dict]) -> dict:
    """LLM 답(dict 목록) + 근거 -> State에 넣을 결과. LLM 없이도 테스트할 수 있게 분리."""
    evidence_by_id = {e["id"]: e for e in evidence}
    scores = {a["item"]: score_item(a, evidence_by_id) for a in answers}
    for code in set(RUBRIC) - set(scores):  # LLM이 빠뜨린 항목은 찾지 못함(0점)으로 두고 이유에 남긴다
        scores[code] = score_item(
            {"item": code, "q1_neg": False, "q2_pos": False, "q3_partial": False,
             "q4_concern": False, "evidence_ids": [], "reason": "LLM 답 없음"}, evidence_by_id)
    result = decide(scores)
    return {
        "scores": scores,
        "total": total_score(scores),
        "verdict": result["verdict"],
        "evaluations": [{
            "company_id": company["company_id"], "name": company["name"],
            "total": result["total"], "score100": result["score100"],
            "verdict": result["verdict"], "reasons": result["reasons"],
            "reconsider": result["reconsider"], "sensitivity": sensitivity(scores),
        }],
    }


def judge_node(state: dict) -> dict:
    company = state["company"]
    evidence = [e for e in state.get("evidence", []) if e.get("company_id") == company["company_id"]]
    llm = init_chat_model(JUDGE_MODEL, model_provider=JUDGE_PROVIDER, temperature=0)
    out: JudgeOutput = llm.with_structured_output(JudgeOutput).invoke(
        build_prompt(company, evidence)
    )
    return summarize(company, [a.model_dump() for a in out.answers], evidence)
