"""RAG 검색 동작 확인. 먼저 `uv run python -m rag.ingest`로 색인을 만든다.

    uv run pytest tests/test_rag.py -v

정답 쪽은 PDF 뷰어 기준 쪽 번호(1부터)다.
"""
import pytest

import config
from rag.eval import load_questions
from rag.ingest import INDEX_DIR
from rag.search import rag_search

pytestmark = pytest.mark.skipif(
    not (INDEX_DIR / "index.faiss").exists(), reason="색인이 없다: python -m rag.ingest"
)

# 질문·정답 쪽은 data/eval/questions.jsonl (rag.eval과 공유). 상위 3개 안에 정답 쪽 청크가 있어야 한다.
CASES = [(q["query"], q["doc_type"], q["doc_id"], set(q["pages"])) for q in load_questions()]


@pytest.mark.parametrize("query,doc_type,doc_id,pages", CASES)
def test_top3_contains_answer_page(query, doc_type, doc_id, pages):
    hits = rag_search(query, doc_type, k=3)
    got = [(h["chunk_id"].rsplit("-p", 1)[0], h["page"]) for h in hits]
    assert any(d == doc_id and p in pages for d, p in got), f"{got}"


@pytest.mark.parametrize("doc_type,query", [
    ("regulation", "credibility assessment framework for AI models"),
    ("tech", "AI-discovered molecules Phase I success rate"),
    ("market", "probability of success from Phase I to approval"),
])
def test_only_returns_requested_doc_type(doc_type, query):
    allowed = {s["doc"] for s in config.RAG_SOURCES if s["doc_type"] == doc_type}
    hits = rag_search(query, doc_type, k=10)
    assert hits and all(h["doc"] in allowed for h in hits)


def test_hit_shape():
    h = rag_search("기술특례상장", "market", k=1)[0]
    assert set(h) == {"chunk_id", "doc", "page", "text", "score"}
    assert isinstance(h["page"], int) and h["text"] and 0 < h["score"] <= 1


@pytest.mark.parametrize("doc_type", config.DOC_TYPES)
@pytest.mark.parametrize("query", ["바나나 케이크 굽는 방법", "오늘 서울 날씨", "삼성전자 주가 전망", "best pizza recipe in Naples"])
def test_irrelevant_query_returns_empty_list(query, doc_type):
    assert rag_search(query, doc_type) == []


def test_failures_return_empty_list_not_exception():
    assert rag_search("", "tech") == []
    assert rag_search("임상", "nonexistent") == []          # type: ignore[arg-type]
