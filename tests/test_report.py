"""통합 보고서: 문장 구조(계약) · 대표 근거 선택 · 판단 요지 · PDF · 지적 줄 재작성. LLM · 네트워크 없이 돈다."""

import copy
import re
from pathlib import Path

import pymupdf
import pytest

import report.writer as writer
from config import CANDIDATES, ITEMS
from judge.node import summarize
from report.pdf import MAX_PAGES, render_report
from report.references import CitationIndex, domain_of, format_reference
from report.writer import (CompanySummary, RewriteOutput, SummarySentence, build_sections,
                           report_node, revise_sections)

NAMES = {c["company_id"]: c["name"] for c in CANDIDATES}


@pytest.fixture(autouse=True)
def no_real_llm(monkeypatch):
    # 주입을 빠뜨린 테스트가 실제 LLM을 부르지 않게 막는다.
    def forbidden(*args, **kwargs):
        raise RuntimeError("테스트에서 실제 LLM을 부르면 안 된다")

    monkeypatch.setattr(writer, "_chat_model", forbidden)


# ---------- 가짜 State ----------

def make_evidence(company_id, code, n=1, *, status="확인됨", host=None, fact=None, quote=None,
                  title=None, published="2026-09-01"):
    host = host or f"{company_id}-{code}-{n}.com"
    if fact is None:
        fact = f"{company_id} {code} 사실 {n}: " + "상세하게 확인된 내용 " * 6
    return {
        "id": f"{company_id}-{code}-{n:03d}", "company_id": company_id, "item": code, "fact": fact,
        "quote": f"{code} 원문 인용 {n}" if quote is None else quote, "status": status,
        "source": f"https://{host}/{company_id}/{code}/{n}", "page": None, "published": published,
        "accessed": "2026-10-13", "title": title,
    }


def judge(company, evidence, *, pos=(), partial=(), neg=(), concern=()):
    """실제 scorer로 판정한다. LLM의 예·아니오 답만 직접 정해 준다."""
    answers = []
    for code in ITEMS:
        ids = [e["id"] for e in evidence if e["item"] == code]
        answers.append({"item": code, "q1_neg": code in neg, "q2_pos": code in pos,
                        "q3_partial": code in partial, "q4_concern": code in concern,
                        "evidence_ids": ids, "reason": "근거 확인"})
    out = summarize(company, answers, evidence)
    return out["evaluations"][0], out["scores"]


def make_state():
    """적격 · 보류(기업 주장만, 우려 -1) · 부적격(관문 -2) · 보류(+4점, 기준선 +4에서 적격)."""
    standigm = [make_evidence("standigm", code, title=f"스탠다임 {code} 기사") for code in ITEMS]
    diagen = [make_evidence("diagen", code, status="기업 주장만", host=f"diagen-site{i % 3}.com")
              for i, code in enumerate(ITEMS)]
    galux = [make_evidence("galux", code) for code in ITEMS]
    drnoah = [make_evidence("drnoah", code) for code in ("management", "technology", "regulation", "sales")]
    plans = [
        (standigm, dict(pos=tuple(ITEMS))),
        (diagen, dict(pos=tuple(c for c in ITEMS if c != "litigation"), concern=("litigation",))),
        (galux, dict(pos=tuple(ITEMS), neg=("technology",))),
        (drnoah, dict(partial=("management", "technology", "regulation", "sales"))),
    ]
    evidence, evaluations, scores = [], [], {}
    for company, (items, answers) in zip(CANDIDATES, plans):
        evaluation, company_scores = judge(company, items, **answers)
        evidence += items
        evaluations.append(evaluation)
        scores[company["company_id"]] = company_scores
    return {"candidates": CANDIDATES, "evaluations": evaluations, "scores_by_company": scores,
            "evidence": evidence, "trace_id": "t-001"}


def fake_summary(evaluation, evidence):
    # 실제 요지 프롬프트처럼 기업 주장은 "~라고 밝혔다"로 귀속한다
    return [
        {"text": f"{evaluation['name']}은 {evidence[0]['fact']}라고 밝혔다.", "evidence_ids": [evidence[0]["id"]]},
        {"text": f"{evaluation['name']}은 {evidence[1]['fact']}라고 밝혔다.", "evidence_ids": [evidence[1]["id"]]},
    ]


def no_summary(evaluation, evidence):
    return []


@pytest.fixture(scope="module")
def state():
    return make_state()


@pytest.fixture(scope="module")
def sections(state):
    return build_sections(state, fake_summary)


def all_lines(sections):
    return list(sections["summary"]) + [line for ch in sections["chapters"] for line in ch["lines"]]


def line_of(sections, line_id):
    return next(line for line in all_lines(sections) if line["id"] == line_id)


def markers(text):
    return [int(n) for n in re.findall(r"\[(\d+)\]", text)]


def check_citations(sections, evidence_by_id):
    """quality 규칙과 같은 기준: 본문 [n] = citations, 참고문헌에 있는 번호, 쓰이지 않는 참고문헌 없음."""
    numbers = [ref["number"] for ref in sections["references"]]
    assert numbers == list(range(1, len(numbers) + 1))
    used = set()
    for line in all_lines(sections):
        if line["kind"] == "fact":
            assert line["evidence_ids"] and line["citations"]
            assert all(i in evidence_by_id for i in line["evidence_ids"])
        assert set(markers(line["text"])) == set(line["citations"])
        used |= set(line["citations"])
    assert used == set(numbers)


# ---------- build_sections: 계약 형식 ----------

def test_sections_follow_contract(state, sections):
    before = copy.deepcopy(state)
    assert build_sections(state, fake_summary) == sections and state == before  # 같은 입력이면 같은 결과, State는 그대로
    assert sections["title"] == "AI 신약개발 스타트업 투자 심사 보고서" and sections["revision"] == 0
    assert [c["key"] for c in sections["chapters"]] == [f"chapter{n}" for n in range(1, 6)]
    assert [c["title"] for c in sections["chapters"]] == [
        "1. 기업 개요와 팀", "2. 시장 · 경쟁 리스크", "3. 기술 · 규제 리스크",
        "4. 리스크 종합과 투자 판단", "5. 한계점"]

    lines = all_lines(sections)
    ids = [line["id"] for line in lines]
    assert len(ids) == len(set(ids))
    assert all(set(line) == {"id", "kind", "company_id", "text", "evidence_ids", "citations"} for line in lines)
    assert all(line["kind"] in ("fact", "note") for line in lines)
    assert all(not line["evidence_ids"] and not line["citations"] for line in lines if line["kind"] == "note")

    evidence_by_id = {e["id"]: e for e in state["evidence"]}
    check_citations(sections, evidence_by_id)
    for line in lines:
        if line["kind"] == "fact":
            owners = {evidence_by_id[i]["company_id"] for i in line["evidence_ids"]}
            assert owners == {line["company_id"]}
            assert line["text"].endswith("".join(f"[{n}]" for n in line["citations"]))

    for ref in sections["references"]:
        assert set(ref) == {"number", "source", "page", "published", "accessed", "title", "evidence_ids"}
        assert ref["source"] == evidence_by_id[ref["evidence_ids"][0]]["source"]
    titled = {ref["title"] for ref in sections["references"]} - {None}
    assert "스탠다임 management 기사" in titled


def test_every_company_appears_in_each_item_chapter(sections):
    for chapter in sections["chapters"][:3]:
        assert {line["company_id"] for line in chapter["lines"]} == set(NAMES)
        assert all(line["text"].startswith(NAMES[line["company_id"]]) for line in chapter["lines"])


def test_summary_is_conclusion_only(sections):
    summary = sections["summary"]
    assert [line["id"] for line in summary] == [f"sum-{n:03d}" for n in range(1, 7)]
    assert all(line["kind"] == "note" and not line["citations"] for line in summary)
    assert summary[0]["text"] == "적격 1곳(스탠다임) · 보류 2곳 · 부적격 1곳 | 평가 4곳"
    for line, company in zip(summary[1:5], CANDIDATES):
        assert line["company_id"] == company["company_id"]
        assert line["text"].startswith(f"{company['name']}: ") and line["text"].endswith("(→ 4장)")
    assert "스탠다임: 적격 +24점" in summary[1]["text"] and "갤럭스: 부적격 +20점" in summary[3]["text"]
    assert "관문 항목 기술이 확인된 근거로" in summary[3]["text"]
    assert summary[5]["text"].startswith("재검토 조건: 보류 기업(디어젠, 닥터노아바이오텍)")
    joined = " ".join(line["text"] for line in summary)
    assert "이 보고서는" not in joined and "목적으로" not in joined


def test_chapter4_has_table_and_notes(state, sections):
    chapter = sections["chapters"][3]
    assert chapter["table"] == [
        {"item": e["name"], "score": e["total"], "status": e["verdict"], "citation": f"{e['score100']}/100"}
        for e in state["evaluations"]]
    notes = [line["text"] for line in chapter["lines"] if line["kind"] == "note"]
    standigm_notes = [t for t in notes if t.startswith("스탠다임")]
    assert [t.split(" ")[1] for t in standigm_notes] == ["관문·영역", "판정", "재검토"]
    assert any(t.startswith("디어젠 재검토 조건: 기술, 법률·정책 관문을 독립 자료로 +1 이상 확인") for t in notes)
    assert any(t.startswith("판정 기준: 합계 +5점 이상") for t in notes)
    # 닥터노아바이오텍은 합계 +4점이라 기준선 +4에서만 판정이 바뀐다
    assert any(t.startswith("민감도:") and "닥터노아바이오텍(+4점: 보류→적격)" in t and "나머지 3곳" in t
               for t in notes)


def test_chapter5_limits_are_per_company(sections):
    lines = sections["chapters"][4]["lines"]
    by_company = {}
    for line in lines:
        by_company.setdefault(line["company_id"], []).append(line["text"])
    for company_id in NAMES:
        first = by_company[company_id][0]
        assert all(word in first for word in ("찾지 못함", "상충함", "기업 주장만"))
    assert "기업 주장만 12개" in by_company["diagen"][0]
    assert "찾지 못함 8개" in by_company["drnoah"][0]
    assert any("소송 -1점" in t for t in by_company["diagen"])
    assert any("기술 -2점" in t for t in by_company["galux"])
    assert len(by_company[None]) == 4   # 공통 한계 3줄 + 품질 평가 이력 1줄
    assert by_company[None][-1].startswith("자동 품질 평가")


def test_sensitivity_line_when_nothing_changes(state):
    stable = copy.deepcopy(state)
    stable["evaluations"][3]["sensitivity"] = {k: stable["evaluations"][3]["verdict"]
                                               for k in stable["evaluations"][3]["sensitivity"]}
    text = next(line["text"] for line in build_sections(stable, no_summary)["chapters"][3]["lines"]
                if line["text"].startswith("민감도"))
    assert "4곳 모두 판정이 같다" in text


def test_missing_evaluation_is_rejected(state):
    partial = {**state, "evaluations": state["evaluations"][:3]}
    with pytest.raises(ValueError, match="닥터노아바이오텍"):
        build_sections(partial, no_summary)


def test_scores_are_optional(state):
    bare = {k: v for k, v in state.items() if k != "scores_by_company"}
    sections = build_sections(bare, no_summary)
    check_citations(sections, {e["id"]: e for e in state["evidence"]})
    # 점수가 없으면 관문 점수만으로 음수 항목을 찾는다
    assert any("기술 -2점" in line["text"] for line in sections["chapters"][4]["lines"])


# ---------- 대표 근거 고르기 ----------

def one_company_state(evidence, scores=None):
    company = CANDIDATES[0]
    evaluation = {"company_id": company["company_id"], "name": company["name"], "total": 3, "score100": 56.2,
                  "verdict": "보류", "reasons": [], "reconsider": [], "sensitivity": {}, "gates": {},
                  "areas": {}, "limits": []}
    return {"candidates": [company], "evaluations": [evaluation], "evidence": evidence,
            "scores_by_company": {company["company_id"]: scores or {}}}


def chosen(sections, line_text_start):
    return next(line for line in sections["chapters"][0]["lines"] + sections["chapters"][1]["lines"]
                if line["text"].startswith(line_text_start))["evidence_ids"][0]


def test_representative_prefers_judge_used_then_confirmed_then_new_domain():
    cid = "standigm"
    evidence = [
        make_evidence(cid, "management", 1, status="기업 주장만", host="a.com"),
        # 같은 순위(judge가 안 씀, 기업 주장만)에서는 이미 쓴 도메인 a.com을 피한다
        make_evidence(cid, "funding", 1, status="기업 주장만", host="a.com"),
        make_evidence(cid, "funding", 2, status="기업 주장만", host="b.com"),
        # judge가 안 쓴 확인됨이 같은 도메인 a.com이어도 순위가 먼저다
        make_evidence(cid, "reputation", 1, status="확인됨", host="a.com"),
        make_evidence(cid, "reputation", 2, status="기업 주장만", host="c.com"),
        # judge가 쓴 근거가 안 쓴 확인됨보다 먼저다
        make_evidence(cid, "sales", 1, status="기업 주장만", host="b.com"),
        make_evidence(cid, "sales", 2, status="확인됨", host="d.com"),
    ]
    scores = {"sales": {"evidence_ids": ["standigm-sales-001"]}}
    sections = build_sections(one_company_state(evidence, scores), no_summary)
    assert chosen(sections, "스탠다임 · 자금 조달") == "standigm-funding-002"
    assert chosen(sections, "스탠다임 · 평판") == "standigm-reputation-001"
    assert chosen(sections, "스탠다임 · 영업·마케팅") == "standigm-sales-001"


def test_unusable_evidence_is_never_cited():
    cid = "standigm"
    evidence = [
        make_evidence(cid, "management", 1, status="찾지 못함"),
        make_evidence(cid, "funding", 1, fact=""),
        {**make_evidence(cid, "reputation", 1), "source": ""},
        {**make_evidence("diagen", "management", 1)},
        make_evidence(cid, "technology", 1, status="확인됨"),
    ]
    sections = build_sections(one_company_state(evidence), no_summary)
    cited = {i for line in all_lines(sections) for i in line["evidence_ids"]}
    assert cited == {"standigm-technology-001"}


def test_fact_text_rules():
    cid = "standigm"
    evidence = [
        make_evidence(cid, "management", 1, status="기업 주장만", fact="신약을 개발 중이다 [3] 라고 한다"),
        make_evidence(cid, "funding", 1, status="확인됨", fact="2024년 시리즈 B를 유치했다."),
    ]
    sections = build_sections(one_company_state(evidence), no_summary)
    lines = {line["id"]: line["text"] for line in sections["chapters"][0]["lines"]}
    assert lines["ch1-001"] == ("스탠다임 · 경영진: 신약을 개발 중이다 라고 한다 (기업 주장만, 2026-09-01 자료) [1]")
    assert lines["ch1-002"] == "스탠다임 · 자금 조달: 2024년 시리즈 B를 유치했다. (확인됨, 2026-09-01 자료) [2]"
    assert lines["ch1-003"] == "스탠다임 · 평판: 원문 근거를 찾지 못함."


def test_company_without_evidence_and_single_source_notes():
    cid = "standigm"
    only_one_site = [make_evidence(cid, code, 1, host="same.com") for code in ("management", "funding", "sales")]
    state = one_company_state(only_one_site)
    state["candidates"] = CANDIDATES[:2]
    state["evaluations"].append({**state["evaluations"][0], "company_id": "diagen", "name": "디어젠"})
    asked = []
    sections = build_sections(state, lambda e, ev: asked.append(e["company_id"]) or [])
    texts = [line["text"] for line in sections["chapters"][4]["lines"]]
    assert "스탠다임: 본문 인용 출처가 same.com 1곳뿐이라 단일 출처 의존이다." in texts
    assert "디어젠: 본문에 인용한 출처가 없다." in texts
    assert asked == ["standigm"]  # 근거가 없는 기업에는 요지를 묻지 않는다


# ---------- 기업별 판단 요지 (LLM) ----------

def summary_lines(sections, company_id):
    return [line for line in sections["chapters"][3]["lines"] if line["id"].startswith(f"ch4-sum-{company_id}-")]


def test_company_summaries_are_fact_lines(state, sections):
    for company_id in NAMES:
        lines = summary_lines(sections, company_id)
        assert [line["id"] for line in lines] == [f"ch4-sum-{company_id}-1", f"ch4-sum-{company_id}-2"]
        for line in lines:
            assert line["kind"] == "fact" and line["company_id"] == company_id
            assert line["evidence_ids"] and line["citations"]
            assert markers(line["text"]) == line["citations"]
    first = summary_lines(sections, "standigm")[0]
    assert first["text"].startswith("스탠다임은 standigm management 사실 1") and first["text"].endswith("라고 밝혔다. [1]")
    # 요지가 인용한 근거도 REFERENCE에 같은 출처 번호로 실린다
    ref = next(r for r in sections["references"] if r["number"] == first["citations"][0])
    assert first["evidence_ids"][0] in ref["evidence_ids"]


def test_summary_is_passed_only_that_companys_evidence_and_evaluation(state):
    seen = {}

    def spy(evaluation, evidence):
        seen[evaluation["company_id"]] = (evaluation["verdict"], {e["company_id"] for e in evidence})
        return []

    build_sections(state, spy)
    assert seen["standigm"] == ("적격", {"standigm"}) and seen["galux"] == ("부적격", {"galux"})
    assert set(seen) == set(NAMES)


def test_invalid_summary_sentences_are_dropped_and_capped(state):
    def messy(evaluation, evidence):
        ok = evidence[0]["id"]
        return [
            {"text": "목록 밖 id를 쓴 문장이다.", "evidence_ids": [ok, "ghost-id"]},
            {"text": "근거 id가 비었다.", "evidence_ids": []},
            {"text": "id가 빈 문자열이다.", "evidence_ids": [""]},
            {"text": "   ", "evidence_ids": [ok]},
            {"text": "인용 번호는 코드가 [9] 붙인다.", "evidence_ids": [ok, ok, evidence[1]["id"]]},
            {"text": "두 번째 정상 문장이다.", "evidence_ids": [evidence[1]["id"]]},
            {"text": "세 번째 정상 문장이다.", "evidence_ids": [ok]},
            {"text": "네 번째는 상한을 넘는다.", "evidence_ids": [ok]},
        ]

    sections = build_sections(state, messy)
    lines = summary_lines(sections, "diagen")
    assert [line["id"] for line in lines] == [f"ch4-sum-diagen-{n}" for n in (1, 2, 3)]
    first = lines[0]
    assert first["text"].startswith("디어젠: 인용 번호는 코드가 붙인다. [")  # 기업명이 없으면 붙인다
    assert "[9]" not in first["text"] and first["evidence_ids"] == [state["evidence"][12]["id"],
                                                                     state["evidence"][13]["id"]]
    assert len(first["citations"]) == 2 and markers(first["text"]) == first["citations"]
    check_citations(sections, {e["id"]: e for e in state["evidence"]})


@pytest.mark.parametrize("failure", [RuntimeError("API 오류"), ValueError("형식 오류")])
def test_summary_failure_skips_only_that_company(state, failure):
    def flaky(evaluation, evidence):
        if evaluation["company_id"] == "diagen":
            raise failure
        return fake_summary(evaluation, evidence)

    sections = build_sections(state, flaky)
    assert summary_lines(sections, "diagen") == []
    assert all(summary_lines(sections, c) for c in ("standigm", "galux", "drnoah"))
    check_citations(sections, {e["id"]: e for e in state["evidence"]})


def test_summary_accepts_pydantic_and_dict_outputs(state):
    def as_model(evaluation, evidence):
        return CompanySummary(sentences=[SummarySentence(text=f"{evaluation['name']} 요지다.",
                                                         evidence_ids=[evidence[0]["id"]])])

    def as_dict(evaluation, evidence):
        return {"sentences": [{"text": f"{evaluation['name']} 요지다.", "evidence_ids": [evidence[0]["id"]]}]}

    for source in (as_model, as_dict):
        sections = build_sections(state, source)
        assert [len(summary_lines(sections, c)) for c in NAMES] == [1, 1, 1, 1]


# ---------- 참고문헌 ----------

def test_citation_index_keeps_title_and_shares_numbers():
    index = CitationIndex()
    first = make_evidence("standigm", "management", 1, host="a.com", title=None, published=None)
    same_source = {**make_evidence("standigm", "funding", 1, host="a.com"), "source": first["source"],
                   "title": "나중에 알게 된 제목", "published": "2026-01-02"}
    assert index.cite(first) == "[1]" and index.add(same_source) == 1
    assert index.add(make_evidence("diagen", "sales", 1, host="b.com")) == 2
    entry = index.entries[0]
    assert entry["title"] == "나중에 알게 된 제목" and entry["published"] == "2026-01-02"
    assert entry["evidence_ids"] == [first["id"], same_source["id"]]
    with pytest.raises(ValueError, match="출처가 없습니다"):
        index.add({"id": "x", "source": "  "})


def test_reference_format_follows_assignment_style():
    web = {"number": 1, "source": "https://www.thebell.co.kr/front/news.asp?key=1", "page": None,
           "published": "2023-04-04", "title": "스탠다임 대표 선임. ", "accessed": "2026-10-13"}
    assert format_reference(web) == ("[1] thebell.co.kr(2023-04-04). 스탠다임 대표 선임. "
                                     "thebell.co.kr, https://www.thebell.co.kr/front/news.asp?key=1")
    bare = {**web, "number": 2, "published": None, "title": None, "source": "https://m.blog.naver.com/a/1"}
    assert format_reference(bare) == "[2] naver.com(n.d.). naver.com, https://m.blog.naver.com/a/1 열람 2026-10-13."
    document = {"number": 3, "source": "FDA_expedited_programs_2014", "page": 12, "published": None, "title": None}
    assert format_reference(document) == "[3] FDA_expedited_programs_2014(n.d.). p.12"


@pytest.mark.parametrize("source, domain", [
    ("https://www.thebell.co.kr/a", "thebell.co.kr"),
    ("https://news.bizwatch.co.kr/a", "bizwatch.co.kr"),
    ("https://m.blog.naver.com/a", "naver.com"),
    ("https://v.daum.net/a?f=p", "daum.net"),
    ("https://example.org", "example.org"),
    ("http://[broken", "http://[broken"),
    ("지원사업 안내서", "지원사업 안내서"),
])
def test_domain_of(source, domain):
    assert domain_of(source) == domain


# ---------- PDF ----------

def pdf_text(path):
    with pymupdf.open(path) as doc:
        return [page.get_text() for page in doc]


def test_render_is_one_flowing_pdf_within_ten_pages(sections, tmp_path):
    path = tmp_path / "report.pdf"
    pages = render_report(sections, path)
    texts = pdf_text(path)
    assert 1 < pages <= MAX_PAGES and len(texts) == pages
    for number, text in enumerate(texts, start=1):
        assert f"{number} / {pages}" in text
    whole = "\n".join(texts)
    order = ["SUMMARY", "1. 기업 개요와 팀", "2. 시장 · 경쟁 리스크", "3. 기술 · 규제 리스크",
             "4. 리스크 종합과 투자 판단", "5. 한계점", "REFERENCE"]
    positions = [whole.index(heading) for heading in order]
    assert positions == sorted(positions)
    assert "스탠다임" in whole and "디어젠" in whole and "갤럭스" in whole and "닥터노아바이오텍" in whole
    assert "standigm-management-1.com" in whole  # REFERENCE에 출처가 실린다
    with pymupdf.open(path) as doc:
        assert doc.metadata["title"] == sections["title"]
        for page in doc:
            for block in page.get_text("dict")["blocks"]:
                for line in block.get("lines", []):
                    for span in line["spans"]:
                        assert span["bbox"][2] <= page.rect.width - 20
                        if span["bbox"][1] < page.rect.height - 30:  # 꼬리말이 아닌 본문
                            assert span["bbox"][3] <= page.rect.height - 40


def test_heading_never_stays_alone_at_the_bottom_of_a_page(sections):
    """쪽 끝에 남은 자리를 바꿔 가며, 제목과 뒤따르는 표 · 문단이 같은 쪽에 놓이는지 본다."""
    from report.pdf import BOTTOM, _Report, _table_cells

    cells = _table_cells(sections["chapters"][3]["table"])
    table_height = sum(height for _, height in cells)
    # 표가 오는 제목은 남은 자리가 제목+표보다 작은 구간(약 76~150pt), 문단이 오는 제목은 제목+두어 줄보다 작은 구간이 위험하다.
    cases = [("table", remaining) for remaining in range(60, 170, 10)]
    cases += [("text", remaining) for remaining in range(30, 110, 20)]
    for follow, remaining in cases:
        report = _Report("제목")
        try:
            report.y = BOTTOM - remaining
            if follow == "table":
                report.heading("4. 리스크 종합과 투자 판단", keep=table_height)
                heading_page = report.page.number
                report.table(cells)
            else:
                report.heading("2. 시장 · 경쟁 리스크")
                heading_page = report.page.number
                report.bullets(["스탠다임 · 영업·마케팅: 원문 근거를 찾지 못함."])
            assert report.page.number == heading_page, (follow, remaining)
        finally:
            report.doc.close()


def test_render_keeps_chapter4_heading_with_its_table(sections, tmp_path):
    """1장 분량을 바꿔 4장 제목이 쪽 끝에 걸리게 해도, 제목과 표의 머리글은 같은 쪽에 있다."""
    note = {"id": "x", "kind": "note", "company_id": None, "text": "채움 문장입니다.",
            "evidence_ids": [], "citations": []}

    def chapter(n, count=1, **extra):
        return {"key": f"chapter{n}", "title": f"{n}. 장", **extra,
                "lines": [dict(note, id=f"ch{n}-{i:03d}") for i in range(count)]}

    for count in range(17, 23):  # 4장 제목이 첫 쪽 끝에서 표 높이 안쪽(18~21줄)으로 들어오는 구간을 지난다
        report = {"title": "제목", "revision": 0, "summary": [dict(note, id="sum-001")], "references": [],
                  "chapters": [chapter(1, count), chapter(2), chapter(3),
                               chapter(4, table=sections["chapters"][3]["table"]), chapter(5)]}
        path = tmp_path / f"flow{count}.pdf"
        render_report(report, path)
        with pymupdf.open(path) as doc:
            heading = next(page for page in doc if page.search_for("4. 장"))
            assert heading.search_for("환산 점수"), f"1장 {count}줄: 4장 제목과 표가 다른 쪽에 갈라졌다"


def test_summary_takes_less_than_half_a_page(sections, tmp_path):
    path = tmp_path / "half.pdf"
    render_report(sections, path)
    with pymupdf.open(path) as doc:
        first = doc[0]
        heading = first.search_for("1. 기업 개요와 팀")[0]
        assert heading.y0 < first.rect.height / 2


def test_worst_case_volume_fits_in_ten_pages(tmp_path):
    """기업 4곳 x 12항목이 모두 긴 근거(출처 48건)이고 요지도 기업마다 3문장일 때."""
    long_fact = ("신약 후보물질 발굴 플랫폼을 고도화하고 해외 제약사와 공동연구를 진행하며 임상 단계 진입을 준비하고 있다고 "
                 "밝혔고, 관련 기사는 투자 유치 규모와 일정까지 상세히 전했다. " * 2)
    evidence, evaluations, scores = [], [], {}
    for company in CANDIDATES:
        cid = company["company_id"]
        items = [make_evidence(cid, code, status="기업 주장만", host=f"news-{cid}-{code}.co.kr",
                               fact=f"{company['name']}의 {ITEMS[code][0]} — {long_fact}", quote=long_fact[:120],
                               title=f"{company['name']} {ITEMS[code][0]} 관련 보도 제목이 길게 이어지는 경우")
                 for code in ITEMS]
        evaluation, company_scores = judge(company, items, pos=tuple(ITEMS), concern=("litigation",))
        evidence += items
        evaluations.append(evaluation)
        scores[cid] = company_scores

    def three_sentences(evaluation, items):
        return [{"text": f"{evaluation['name']}은 평가 기준상 {evaluation['verdict']}이며 {long_fact}",
                 "evidence_ids": [item["id"]]} for item in items[:3]]

    state = {"candidates": CANDIDATES, "evaluations": evaluations, "scores_by_company": scores,
             "evidence": evidence}
    sections = build_sections(state, three_sentences)
    assert len(sections["references"]) == 48
    assert 1 < render_report(sections, tmp_path / "worst.pdf") <= MAX_PAGES


def test_short_report_is_not_padded_to_one_page_per_chapter(tmp_path):
    line = {"id": "x", "kind": "note", "company_id": None, "text": "짧은 문장", "evidence_ids": [], "citations": []}
    sections = {"title": "제목", "revision": 0, "summary": [dict(line, id="sum-001")],
                "chapters": [{"key": f"chapter{n}", "title": f"{n}. 장", "lines": [dict(line, id=f"ch{n}-001")]}
                             for n in range(1, 6)], "references": []}
    assert render_report(sections, tmp_path / "short.pdf") == 1
    text = pdf_text(tmp_path / "short.pdf")[0]
    assert "본문에서 개별 외부 자료를 직접 인용하지 않음" in text
    assert "1 / 1" in text  # 꼬리말의 전체 쪽수는 렌더 뒤에 채운다


def test_render_rejects_more_than_ten_pages_without_saving(tmp_path):
    long_line = {"id": "x", "kind": "note", "company_id": None, "text": "긴 문장입니다. " * 60,
                 "evidence_ids": [], "citations": []}
    sections = {"title": "제목", "revision": 0, "summary": [dict(long_line, id="sum-001")],
                "chapters": [{"key": "chapter1", "title": "1. 장",
                              "lines": [dict(long_line, id=f"ch1-{n:03d}") for n in range(120)]}],
                "references": []}
    path = tmp_path / "too_long.pdf"
    with pytest.raises(ValueError, match="10쪽"):
        render_report(sections, path)
    assert not path.exists()


# ---------- revise_sections: 지적받은 줄만 고친다 ----------

def flag(line_id, check, reason="사유", suggestion="제안"):
    return {"line_id": line_id, "check": check, "reason": reason, "suggestion": suggestion}


def neutral_rewrite(requests):
    return [{"line_id": r["line_id"], "text": f"중립으로 고쳤다고 밝혔다 [9] ({r['line_id']})"} for r in requests]


def changed_ids(before, after):
    """지적받은 줄 중 바뀐 것. 5장 품질 평가 이력 문장은 판마다 바뀌므로 따로 확인한다."""
    old = {line["id"]: line for line in all_lines(before) if line["id"] != writer.QUALITY_NOTE_ID}
    new = {line["id"]: line for line in all_lines(after) if line["id"] != writer.QUALITY_NOTE_ID}
    return {i for i in old if i not in new or old[i] != new[i]}


def test_groundedness_replaces_line_with_source_quote(state, sections):
    evidence_by_id = {e["id"]: e for e in state["evidence"]}
    target = line_of(sections, "ch1-002")
    before = copy.deepcopy(sections)
    revised = revise_sections(sections, {"flagged_lines": [flag("ch1-002", "groundedness")]}, evidence_by_id,
                              rewrite=lambda requests: pytest.fail("중립 재작성은 호출되면 안 된다"))
    quote = evidence_by_id[target["evidence_ids"][0]]["quote"]
    new = line_of(revised, "ch1-002")
    # 이름표(기업 · 항목)와 근거 상태 표기는 남기고 본문만 원문 인용으로 바뀐다
    assert new["text"].startswith("스탠다임 · ") and f'원문 — "{quote}" (' in new["text"]
    assert new["text"].endswith(f"[{target['citations'][0]}]")
    assert new["kind"] == "fact" and new["evidence_ids"] == target["evidence_ids"]
    assert changed_ids(before, revised) == {"ch1-002"}
    assert revised["revision"] == 1 and sections == before  # 입력은 바뀌지 않는다
    check_citations(revised, evidence_by_id)


def test_groundedness_without_quote_deletes_line_and_prunes_references(state, sections):
    evidence_by_id = copy.deepcopy({e["id"]: e for e in state["evidence"]})
    cited_by = {}
    for line in all_lines(sections):
        for n in line["citations"]:
            cited_by.setdefault(n, []).append(line["id"])
    solo = next(line for line in all_lines(sections) if line["kind"] == "fact"
                and all(cited_by[n] == [line["id"]] for n in line["citations"]))
    evidence_by_id[solo["evidence_ids"][0]]["quote"] = ""
    before_count = len(sections["references"])

    revised = revise_sections(sections, {"flagged_lines": [flag(solo["id"], "groundedness")]}, evidence_by_id)
    assert solo["id"] not in {line["id"] for line in all_lines(revised)}
    assert len(revised["references"]) == before_count - 1
    check_citations(revised, evidence_by_id)  # 번호가 1부터 다시 이어지고 모두 본문에서 쓰인다
    removed_source = next(r["source"] for r in sections["references"] if r["number"] == solo["citations"][0])
    assert removed_source not in [r["source"] for r in revised["references"]]
    later = [line for line in all_lines(sections) if line["kind"] == "fact" and line["citations"][0] > solo["citations"][0]]
    assert later and all(line_of(revised, line["id"])["citations"][0] == line["citations"][0] - 1 for line in later)


def test_deleting_a_line_keeps_a_reference_that_other_lines_still_cite(state, sections):
    evidence_by_id = copy.deepcopy({e["id"]: e for e in state["evidence"]})
    shared = line_of(sections, "ch1-001")  # 4장 요지도 같은 근거를 인용한다
    evidence_by_id[shared["evidence_ids"][0]]["quote"] = ""
    revised = revise_sections(sections, {"flagged_lines": [flag("ch1-001", "groundedness")]}, evidence_by_id)
    assert len(revised["references"]) == len(sections["references"])
    check_citations(revised, evidence_by_id)


def test_neutrality_rewrites_with_llm_and_restores_citation_numbers(state, sections):
    evidence_by_id = {e["id"]: e for e in state["evidence"]}
    seen = []

    def rewrite(requests):
        seen.extend(requests)
        return neutral_rewrite(requests)

    flagged = [flag("ch3-001", "neutrality", "과장 수식어", "수식어를 뺀다"),
               flag("ch4-sum-diagen-2", "neutrality")]
    before = copy.deepcopy(sections)
    revised = revise_sections(sections, {"flagged_lines": flagged}, evidence_by_id, rewrite=rewrite)

    original = line_of(before, "ch3-001")
    request = next(r for r in seen if r["line_id"] == "ch3-001")
    assert request["company"] == "스탠다임" and request["text"] == original["text"]
    assert request["reason"] == "과장 수식어" and request["suggestion"] == "수식어를 뺀다"
    assert request["quotes"] == [evidence_by_id[original["evidence_ids"][0]]["quote"]]
    n = original["citations"][0]
    text = line_of(revised, "ch3-001")["text"]
    # LLM의 [9]는 지우고 원래 번호, 지워진 근거 상태 표기는 코드가 다시 붙인다
    assert text.startswith("중립으로 고쳤다고 밝혔다 (ch3-001) (") and text.endswith(f") [{n}]")
    assert line_of(revised, "ch3-001")["citations"] == original["citations"]
    assert changed_ids(before, revised) == {"ch3-001", "ch4-sum-diagen-2"}  # 판단 요지 문장도 같은 경로
    assert revised["revision"] == 1
    check_citations(revised, evidence_by_id)


@pytest.mark.parametrize("shape", ["list", "mapping", "model"])
def test_rewrite_output_shapes(state, sections, shape):
    def rewrite(requests):
        pairs = {r["line_id"]: "중립 문장" for r in requests}
        if shape == "mapping":
            return pairs
        lines = [{"line_id": k, "text": v} for k, v in pairs.items()]
        return RewriteOutput(lines=lines) if shape == "model" else lines

    revised = revise_sections(sections, {"flagged_lines": [flag("ch2-003", "neutrality")]},
                              {e["id"]: e for e in state["evidence"]}, rewrite=rewrite)
    assert line_of(revised, "ch2-003")["text"].startswith("중립 문장 (")


def test_note_lines_and_unknown_ids_are_left_alone(state, sections):
    evidence_by_id = {e["id"]: e for e in state["evidence"]}
    flagged = [flag("sum-002", "groundedness"), flag("ghost-line", "groundedness"),
               flag("ch5-001", "groundedness")]
    revised = revise_sections(sections, {"flagged_lines": flagged}, evidence_by_id,
                              rewrite=lambda requests: pytest.fail("호출되면 안 된다"))
    assert changed_ids(sections, revised) == set() and revised["revision"] == 1


def test_both_checks_on_one_line_use_the_quote_only(state, sections):
    evidence_by_id = {e["id"]: e for e in state["evidence"]}
    both = [flag("ch1-004", "neutrality"), flag("ch1-004", "groundedness")]
    revised = revise_sections(sections, {"flagged_lines": both}, evidence_by_id,
                              rewrite=lambda requests: pytest.fail("호출되면 안 된다"))
    assert line_of(revised, "ch1-004")["text"].startswith("디어젠 · ") and "원문 — " in line_of(revised, "ch1-004")["text"]


def test_empty_flags_still_count_as_a_revision(state, sections):
    revised = revise_sections(sections, {"flagged_lines": []}, {e["id"]: e for e in state["evidence"]})
    assert revised["revision"] == 1 and changed_ids(sections, revised) == set()


def test_failed_or_empty_rewrite_keeps_the_line(state, sections):
    evidence_by_id = {e["id"]: e for e in state["evidence"]}

    def broken(requests):
        raise RuntimeError("API 오류")

    for rewrite in (broken, lambda requests: [], lambda requests: [{"line_id": "ch1-001", "text": " [3] "}]):
        revised = revise_sections(sections, {"flagged_lines": [flag("ch1-001", "neutrality")]}, evidence_by_id,
                                  rewrite=rewrite)
        assert changed_ids(sections, revised) == set() and revised["revision"] == 1


def test_company_names_come_from_candidates(state, sections):
    """이름표(기업 · 항목)가 없는 줄(판단 요지 등)은 names의 기업명을 붙인다."""
    sections = copy.deepcopy(sections)
    line = line_of(sections, "ch1-001")
    line["text"] = line["text"].split(": ", 1)[1]
    revised = revise_sections(sections, {"flagged_lines": [flag("ch1-001", "groundedness")]},
                              {e["id"]: e for e in state["evidence"]}, names={"standigm": "다른이름"})
    assert line_of(revised, "ch1-001")["text"].startswith("다른이름: 원문 — ")


# ---------- report_node ----------

def test_report_node_first_write_and_rewrite(state, tmp_path, monkeypatch):
    monkeypatch.setattr(writer, "OUTPUT_DIR", tmp_path)
    first = report_node(state, summarize_company=fake_summary)
    assert set(first) == {"report_sections", "report_path", "report_pages", "report_revisions"}
    assert first["report_revisions"] == 0 and first["report_sections"]["revision"] == 0
    assert first["report_path"] == str(tmp_path / "t-001_report.pdf") and Path(first["report_path"]).is_file()
    assert first["report_pages"] == len(pdf_text(first["report_path"])) <= MAX_PAGES

    quality = {"passed": False, "revision": 0, "flagged_lines": [flag("ch1-001", "neutrality")]}
    again = report_node({**state, **first, "quality": quality}, rewrite=neutral_rewrite,
                        summarize_company=lambda *args: pytest.fail("재작성에서 처음부터 다시 쓰면 안 된다"))
    assert again["report_revisions"] == 1 and again["report_sections"]["revision"] == 1
    assert again["report_path"] == first["report_path"]
    assert changed_ids(first["report_sections"], again["report_sections"]) == {"ch1-001"}
    assert "중립으로 고쳤다고 밝혔다 (ch1-001)" in " ".join("\n".join(pdf_text(again["report_path"])).split())

    passed = {**state, **first, "quality": {**quality, "passed": True}}
    assert report_node(passed, summarize_company=fake_summary)["report_revisions"] == 0


def test_report_node_path_is_relative_to_project_and_trace_id_is_safe(state, tmp_path, monkeypatch):
    monkeypatch.setattr(writer, "ROOT", tmp_path)
    monkeypatch.setattr(writer, "OUTPUT_DIR", tmp_path / "outputs")
    update = report_node({k: v for k, v in state.items() if k != "trace_id"}, summarize_company=no_summary)
    assert update["report_path"] == "outputs/local_report.pdf"
    update = report_node({**state, "trace_id": "../run 1"}, summarize_company=no_summary)
    assert update["report_path"] == "outputs/.._run_1_report.pdf"
    assert (tmp_path / "outputs" / ".._run_1_report.pdf").is_file()


# ---------- 실제 LLM 호출부(가짜 모델로 연결만 확인) ----------

class StubChat:
    def __init__(self, answer):
        self.answer, self.prompts, self.schemas = answer, [], []

    def with_structured_output(self, schema):
        self.schemas.append(schema)
        return self

    def invoke(self, prompt):
        self.prompts.append(prompt)
        return self.answer(prompt, self.schemas[-1])


def test_default_summary_llm_path(state, monkeypatch):
    def answer(prompt, schema):
        first_id = re.search(r"\[([a-z]+-[a-z]+-\d{3})\]", prompt.split("## 근거 목록")[1]).group(1)
        return CompanySummary(sentences=[SummarySentence(text="요지 문장이다.", evidence_ids=[first_id])])

    stub = StubChat(answer)
    monkeypatch.setattr(writer, "_chat_model", lambda: stub)
    sections = build_sections(state)
    assert all(len(summary_lines(sections, c)) == 1 for c in NAMES)
    assert set(stub.schemas) == {CompanySummary} and len(stub.prompts) == 4


def test_summary_prompt_carries_verdict_rules_and_trimmed_quotes(state):
    evidence = [make_evidence("diagen", "technology", 1, status="기업 주장만", quote="가" * 400 + " [4]")]
    evaluation = next(e for e in state["evaluations"] if e["company_id"] == "diagen")
    prompt = writer._summary_prompt(evaluation, evidence)
    assert not any(slot in prompt for slot in ("{company}", "{evaluation}", "{evidence}"))
    assert f"판정: 보류 (합계 {evaluation['total']:+d}점" in prompt
    assert "판정 사유: 관문 기술, 법률·정책 확인 근거 부족" in prompt
    assert "재검토 조건: 기술, 법률·정책 관문을 독립 자료로 +1 이상 확인" in prompt
    assert "[diagen-technology-001] (기업 주장만)" in prompt and "가" * 150 in prompt and "가" * 151 not in prompt
    for rule in ("판정 · 점수 · 판정 사유 · 재검토 조건은 쓰지 않는다", "evidence_ids", "기업 주장만"):
        assert rule in writer.SUMMARY_PROMPT


def test_default_rewrite_llm_path(state, sections, monkeypatch):
    stub = StubChat(lambda prompt, schema: RewriteOutput(lines=[
        {"line_id": "ch3-001", "text": "스탠다임은 플랫폼을 활용한다고 밝혔다. (기업 주장만)"}]))
    monkeypatch.setattr(writer, "_chat_model", lambda: stub)
    revised = revise_sections(sections, {"flagged_lines": [flag("ch3-001", "neutrality", "과장", "고쳐라")]},
                              {e["id"]: e for e in state["evidence"]})
    # LLM이 근거 상태 표기를 바꿔 써도(확인됨 → 기업 주장만) 원래 상태로 되돌린다. 상태는 LLM이 정하지 않는다
    assert line_of(revised, "ch3-001")["text"].startswith("스탠다임은 플랫폼을 활용한다고 밝혔다. (확인됨, 2026-09-01 자료) [")
    prompt = stub.prompts[0]
    assert "[ch3-001] 기업: 스탠다임" in prompt and "지적 사유: 과장" in prompt and "수정 제안: 고쳐라" in prompt
    assert "{lines}" not in prompt and "근거 원문: technology 원문 인용 1" in prompt
    assert stub.schemas == [RewriteOutput]


# ---------- quality 노드와의 계약 ----------

def test_report_and_quality_loop_converges(state, tmp_path, monkeypatch):
    evaluator = pytest.importorskip("quality.evaluator")
    monkeypatch.setattr(writer, "OUTPUT_DIR", tmp_path)

    def run_quality(update, grounded=(), neutral=()):
        def judge_lines(items):
            return {"judgments": [{
                "line_id": item["line_id"], "reason": "판정",
                "supported": None if item["kind"] == "note" else item["line_id"] not in grounded,
                "neutral": item["line_id"] not in neutral, "suggestion": "고친다"} for item in items]}

        return evaluator.evaluate(update["report_sections"], state["evidence"], state["evaluations"],
                                  update["report_pages"], judge=judge_lines,
                                  scores_by_company=state["scores_by_company"])

    first = report_node(state, summarize_company=fake_summary)
    quality = run_quality(first, grounded={"ch1-003"}, neutral={"ch4-sum-galux-1"})
    # 규칙 검사(편향 · 형식 · 인용 일치)는 처음부터 통과하고, LLM이 지적한 줄만 남는다
    assert quality["checks"]["bias"]["passed"] and quality["checks"]["format"]["passed"]
    assert not quality["passed"]
    assert {(f["line_id"], f["check"]) for f in quality["flagged_lines"]} == {
        ("ch1-003", "groundedness"), ("ch4-sum-galux-1", "neutrality")}

    second = report_node({**state, **first, "quality": quality}, rewrite=neutral_rewrite)
    assert second["report_revisions"] == 1
    assert run_quality(second)["passed"]


def test_neutral_rewrite_keeps_status_label():
    """재작성 LLM이 문장 끝 근거 상태 표기를 지워도 코드가 다시 붙인다."""
    sections = {"title": "t", "revision": 0, "summary": [], "chapters": [{"key": "chapter1", "title": "1", "lines": [
        {"id": "ch1-001", "kind": "fact", "company_id": "standigm",
         "text": "스탠다임 · 경영진: 국내 최초 AI 신약 개발사다. (확인됨, 2025-07-21 자료) [1]",
         "evidence_ids": ["standigm-management-001"], "citations": [1]}]}],
        "references": [{"number": 1, "source": "https://news.example/a", "page": None, "published": "2025-07-21",
                        "accessed": "2026-10-13", "title": None, "evidence_ids": ["standigm-management-001"]}]}
    quality = {"passed": False, "flagged_lines": [{"line_id": "ch1-001", "check": "neutrality",
                                                   "reason": "과장 수식어 최초 사용", "suggestion": ""}]}
    evidence = {"standigm-management-001": {"id": "standigm-management-001", "quote": "국내 최초 AI 신약 개발사"}}
    revised = writer.revise_sections(sections, quality, evidence,
                                     rewrite=lambda requests: [{"line_id": "ch1-001", "text": "스탠다임 · 경영진: AI 신약 개발사다."}])
    text = revised["chapters"][0]["lines"][0]["text"]
    assert text == "스탠다임 · 경영진: AI 신약 개발사다. (확인됨, 2025-07-21 자료) [1]"
    assert revised["changes"][0]["before"].startswith("스탠다임 · 경영진: 국내 최초")
