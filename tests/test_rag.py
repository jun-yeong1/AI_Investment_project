"""RAG 단위 테스트 — LLM · 임베딩 모델 없이 돈다.  실행: pytest tests/test_rag.py"""
import pytest

from rag.parse_pdfs import clean_page, repeated_lines
from rag.retriever import CHUNK_DIR, get_retriever, kiwi_tokenize
from rag.sources import DOC_TYPES, DOCS
from tools.evidence import make_evidence


def test_clean_page_removes_noise():
    noise = {"Draft — Not for Implementation"}
    raw = "Draft — Not for Implementation\n9\n242\nThe ﬁrst analysis shows that\n243\nmolecules succeed."
    assert clean_page(raw, noise) == "The first analysis shows that molecules succeed."


def test_clean_page_keeps_bullets_on_new_line():
    raw = "□(현황) 복수평가 필요\nㅇ단, 소부장 기업은 단수평가"
    assert clean_page(raw, set()).splitlines() == ["□(현황) 복수평가 필요", "ㅇ단, 소부장 기업은 단수평가"]


def test_repeated_lines_detects_header():
    pages = ["Header\nbody a", "Header\nbody b", "Header\nbody c", "Header\nbody d"]
    assert repeated_lines(pages) == {"Header"}


def test_kiwi_tokenize_lowercases_english():
    tokens = kiwi_tokenize("Fast Track 지정 요건")
    assert "fast" in tokens and "track" in tokens and "지정" in tokens


def test_sources_cover_all_doc_types():
    assert {d["doc_type"] for d in DOCS.values()} == set(DOC_TYPES)


def test_make_evidence_defaults():
    ev = make_evidence(company="갤럭스", fact="x", source_type="rag")
    assert ev["id"].startswith("E") and ev["status"] == "미분류" and len(ev["accessed"]) == 10


@pytest.mark.skipif(not (CHUNK_DIR / "chunks_1000.jsonl").exists(), reason="python -m rag.prepare 먼저")
def test_bm25_returns_only_requested_doc_type():
    for doc_type in DOC_TYPES:
        docs = get_retriever(doc_type, k=3, mode="bm25").invoke("임상 승인 기준")
        assert docs and all(d.metadata["doc_type"] == doc_type for d in docs)
