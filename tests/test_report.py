"""D-2 보고서 분기와 E절의 PDF·인용 계약을 검증한다."""

import pymupdf
import pytest

from config import CANDIDATES, ITEMS
from graph import load_nodes
from judge.node import summarize
from report.pdf import finalize_reports
from report.writer import build_qualified_sections, no_qualified_node, report_node


def _answers(company_id: str, *, positive: bool) -> tuple[list[dict], list[dict]]:
    evidence, answers = [], []
    for code in ITEMS:
        evidence_id = f"{company_id}-{code}-001"
        if positive:
            evidence.append({
                "id": evidence_id, "company_id": company_id, "item": code,
                "fact": f"{code}의 확인된 사실", "quote": "확인된 사실", "status": "확인됨",
                "source": f"https://example.org/{company_id}/{code}/" + "detailed-report-" * 8,
                "page": None,
                "published": "2026-09-01", "accessed": "2026-09-30",
            })
        answers.append({
            "item": code, "q1_neg": False, "q2_pos": positive, "q3_partial": False,
            "q4_concern": False, "evidence_ids": [evidence_id] if positive else [],
            "reason": "근거 확인" if positive else "근거 없음",
        })
    return evidence, answers


def _qualified_state() -> dict:
    company = CANDIDATES[0]
    evidence, answers = _answers(company["company_id"], positive=True)
    judged = summarize(company, answers, evidence)
    evidence.append({
        "id": "unrelated", "company_id": CANDIDATES[1]["company_id"],
        "item": "technology", "fact": "다른 기업 사실", "quote": "다른 기업 사실",
        "status": "확인됨", "source": "https://example.org/unused", "page": None,
        "published": None, "accessed": "2026-09-30",
    })
    return {**judged, "company": company, "current_idx": 0, "evidence": evidence,
            "pipeline": [{"substance": "ST-01", "indication": "폐암", "stage": "임상"}]}


def test_report_node_renders_judge_result_and_only_cited_sources(tmp_path, monkeypatch):
    import report.writer as writer

    monkeypatch.setattr(writer, "OUTPUT_DIR", tmp_path)
    state = _qualified_state()
    sections = build_qualified_sections(state)
    assert sections["summary"][0].startswith("적격 |")
    assert len(sections["chapter4"]["rows"]) == 12
    assert "https://example.org/unused" not in [r["source"] for r in sections["references"]]
    assert all(r["evidence_ids"] for r in sections["references"])

    update = report_node(state)
    with pymupdf.open(update["reports"][0]) as doc:
        assert len(doc) == 5
        text = "\n".join(page.get_text() for page in doc)
        assert "SUMMARY" in text and "4. 리스크 종합과 투자 판단" in text
        assert "REFERENCE" in text and "https://example.org/unused" not in text
        assert text.index("SUMMARY") < text.index("1. 기업 개요와 팀")
        for page in doc:
            spans = [span for block in page.get_text("dict")["blocks"]
                     for line in block.get("lines", []) for span in line["spans"]]
            assert all(span["bbox"][2] <= page.rect.width - 20 for span in spans)


def test_no_qualified_report_compares_four_and_merge_preserves_order(tmp_path, monkeypatch):
    import report.writer as writer

    monkeypatch.setattr(writer, "OUTPUT_DIR", tmp_path)
    evaluations = []
    for company in CANDIDATES:
        evidence, answers = _answers(company["company_id"], positive=False)
        evaluations += summarize(company, answers, evidence)["evaluations"]
    state = {"candidates": CANDIDATES, "evaluations": evaluations, "reports": []}
    no_qualified = no_qualified_node(state)
    with pymupdf.open(no_qualified["reports"][0]) as doc:
        assert len(doc) == 5
        chapter4 = doc[3].get_text()
        assert all(company["name"] in chapter4 for company in CANDIDATES)
        assert "재검토 조건" in chapter4

    qualified = report_node(_qualified_state())
    merged = finalize_reports({"reports": [qualified["reports"][0], no_qualified["reports"][0]]},
                              tmp_path / "combined.pdf")
    with pymupdf.open(merged) as doc:
        assert len(doc) == 10
        assert CANDIDATES[0]["name"] in doc[0].get_text()
        assert "적격 없음" in doc[5].get_text()


def test_report_nodes_are_available_to_graph_and_reject_wrong_verdict():
    nodes = load_nodes()
    assert "report" in nodes and "no_qualified" in nodes
    state = _qualified_state()
    state["verdict"] = "보류"
    with pytest.raises(ValueError, match="적격 기업"):
        report_node(state)
