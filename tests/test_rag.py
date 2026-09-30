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


def test_struct_split_uses_headings_and_keeps_figure_separate():
    from langchain_core.documents import Document
    from rag.parse_pdfs import struct_split
    body = "\n".join(["A. Qualifying Criteria " + "x" * 400, "- detail one", "B. Features " + "y" * 400])
    page = Document(page_content=body + "\n\n[표·그림]\n| a | b |", metadata={"page": 3})
    chunks = [c.page_content for c in struct_split(page)]
    assert chunks[0].startswith("A.") and "- detail one" in chunks[0]      # 하위 글머리는 위 덩어리에
    assert chunks[1].startswith("B.")
    assert chunks[-1].startswith("[표·그림]")                             # 표 · 그림은 따로
    assert all(c.metadata == {"page": 3} for c in struct_split(page))     # 쪽 번호 유지


def test_vision_collapses_repeated_unreadable_lines():
    import re
    text = "제목\n| [판독 불가] |\n| [판독 불가] |\n| [판독 불가] |\n끝"
    out = re.sub(r"(^.*\[판독 불가\].*$\n?){2,}", "[판독 불가 — 그림 속 작은 글자]\n", text, flags=re.M)
    assert out == "제목\n[판독 불가 — 그림 속 작은 글자]\n끝"


def test_vision_sanitize_stops_runaway_output():
    """비전 모델이 표 구분선을 끝없이 이어 쓴 출력(210만 자)을 줄이고 자른다."""
    from rag.vision import MAX_CHARS, _sanitize
    runaway = "| 구분 | 내용 |\n|---|" + "-" * 2_000_000
    out = _sanitize(runaway)
    assert len(out) < 100 and "---" in out
    assert len(_sanitize("가" * (MAX_CHARS + 500))) <= MAX_CHARS + 30
