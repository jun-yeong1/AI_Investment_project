"""RAG 단위 테스트 — LLM · 임베딩 모델 없이 돈다.  실행: pytest tests/test_rag.py"""
import pytest

from rag.parse_pdfs import clean_page, is_line_numbered, repeated_lines
from rag.retriever import CHUNK_DIR, get_retriever, kiwi_tokenize
from rag.sources import DOC_TYPES, DOCS


def test_clean_page_removes_only_editing_marks():
    """줄번호 · 쪽번호 · 반복 머리말은 지우고, 합자는 풀고, 끊긴 문장은 잇는다."""
    raw = "Draft — Not for Implementation\n241\nThe ﬁrst analysis shows that\n242\nmolecules succeed.\n- 7 -"
    out = clean_page(raw, drop={"Draft — Not for Implementation"}, line_numbered=True)
    assert out == "The first analysis shows that molecules succeed."


def test_clean_page_keeps_table_numbers():
    """줄번호 문서가 아니면 표에서 나온 숫자는 지우지 않는다 (정보를 버리지 않는다)."""
    raw = "Phase success\nHematology\n92\n69.6%\nMetabolic\n136\n61.8%\nend of table."
    out = clean_page(raw, drop=set())
    assert "69.6%" in out and "61.8%" in out and "136" in out


def test_is_line_numbered():
    numbered = ["\n".join(f"{n}\ntext line" for n in range(i * 30, i * 30 + 30)) for i in range(3)]
    table = ["Hematology\n92\n69.6%\nMetabolic\n136\n61.8%"] * 3
    assert is_line_numbered(numbered) and not is_line_numbered(table)


def test_clean_page_keeps_bullets_on_new_line():
    raw = "□(현황) 복수평가 필요\nㅇ단, 소부장 기업은 단수평가"
    assert clean_page(raw, set()).splitlines() == ["□(현황) 복수평가 필요", "ㅇ단, 소부장 기업은 단수평가"]


def test_repeated_lines_detects_header_not_table_heading():
    """쪽 가장자리에 반복되는 줄만 머리말. 쪽 가운데 반복되는 표 머리글은 내용이다."""
    pages = [f"Header\nbody {i}\nvalue {i}\nNDA/BLA\nmore {i}\nend {i}\nlast {i}\nfinal {i}" for i in range(4)]
    assert repeated_lines(pages) == {"Header"}


def test_kiwi_tokenize_lowercases_english():
    tokens = kiwi_tokenize("Fast Track 지정 요건")
    assert "fast" in tokens and "track" in tokens and "지정" in tokens


def test_sources_cover_all_doc_types():
    assert {d["doc_type"] for d in DOCS.values()} == set(DOC_TYPES)


@pytest.mark.skipif(not (CHUNK_DIR / "chunks_r1000.jsonl").exists(), reason="python -m rag.prepare --chunk r1000 먼저")
def test_bm25_returns_only_requested_doc_type():
    for doc_type in DOC_TYPES:
        docs = get_retriever(doc_type, k=3, mode="bm25", chunk="r1000").invoke("임상 승인 기준")
        assert docs and all(d.metadata["doc_type"] == doc_type for d in docs)
