"""Agentic RAG 검색 — 팀 계약(rag/types.py)을 따른다.

    from rag.rag_search import rag_search
    hits = rag_search("희귀의약품 지정이 신약 개발 위험에서 어떤 의미인가", "regulation")
    # → list[RagHit]  {"chunk_id", "doc", "page", "text", "score"}
    # 관련 문서가 없으면 [] — 웹 보강은 호출한 에이전트가 [] 를 보고 판단한다.

    # 선택: 기술·파이프라인 에이전트가 찾은 목록을 주면 검색 질문을 물질 · 적응증 단위로 만든다
    hits = rag_search("임상 진입 전 받을 수 있는 규제 지정은?", "regulation",
                      pipeline=state["pipeline"])

흐름 (설계서 B-2 "RAG 에이전트 내부 흐름" — 웹 보강은 에이전트 몫)
    질문 생성(한국어 + 영어) → 검색 → 관련성 채점
        ├ 관련 있음            → RagHit 반환
        ├ 관련 없음, 재작성 전 → 질문 다시 쓰기 → 다시 검색
        └ 관련 없음, 재작성 후 → [] 반환

RAG 문서에는 특정 기업 이야기가 없고 기준 · 제도 · 통계가 들어 있다.
그래서 검색 질문은 기업 이름 대신 일반 개념(제도 이름, 적응증, 개발 단계)으로 바꿔서 만든다.
청킹 · 임베딩 · 검색 방식은 rag/settings.py (실험으로 고른 값), .env 의 OPENAI_API_KEY 필요.
"""
from functools import lru_cache
from typing import TypedDict

from dotenv import load_dotenv
from langchain.chat_models import init_chat_model
from langchain_core.tools import tool
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from rag import settings
from rag.retriever import search
from rag.sources import DOC_TYPES
from rag.types import DocType, RagHit

load_dotenv()


class Queries(BaseModel):
    ko: str = Field(description="한국어 검색 질문")
    en: str = Field(description="English search query")


class Relevance(BaseModel):
    relevant: list[int] = Field(description="질문의 답을 직접 담은 문서 번호. 없으면 빈 목록")


class RagState(TypedDict, total=False):
    question: str
    doc_type: str
    pipeline: list[dict]
    k: int
    queries: list[str]
    tried: list[str]          # 이미 써 본 질문 — 재작성 때 반복하지 않게
    docs: list
    relevant: list
    rewritten: bool


@lru_cache
def _llm():
    return init_chat_model(settings.LLM_MODEL, temperature=0)


def _pipeline_text(pipeline: list[dict]) -> str:
    if not pipeline:
        return "없음"
    return ", ".join(f"{p.get('substance', '?')}({p.get('indication', '?')}, {p.get('stage', '?')})"
                     for p in pipeline)


# ---------- 노드 ----------

def make_queries(s: RagState) -> RagState:
    prompt = (
        f"'{s['doc_type']}' 참고 문서(가이드라인 · 보고서 · 통계)를 검색할 질문을 만든다.\n"
        f"원래 질문: {s['question']}\n"
        f"파이프라인: {_pipeline_text(s.get('pipeline', []))}\n"
        "문서에는 특정 기업 이야기가 없으므로 기업 이름은 빼고, 제도 이름 · 적응증 · 개발 단계 같은 "
        "일반 개념으로 바꿔라. 한국어 질문 하나와 영어 질문 하나를 만든다."
    )
    q = _llm().with_structured_output(Queries).invoke(prompt)
    return {"queries": [q.ko, q.en], "tried": [q.ko, q.en]}


def retrieve(s: RagState) -> RagState:
    return {"docs": search(s["doc_type"], s["queries"], k=s.get("k", 3))}


def grade(s: RagState) -> RagState:
    if not s["docs"]:
        return {"relevant": []}
    listing = "\n\n".join(f"[{i}] ({d.metadata['title']}, p.{d.metadata['page']})\n{d.page_content[:700]}"
                          for i, d in enumerate(s["docs"]))
    prompt = (f"질문: {s['question']}\n\n"
              "아래 문서 중 질문의 답이 되는 내용(수치 · 요건 · 정의 · 사실)을 **직접** 담은 것의 번호만 골라라.\n"
              "- 주제나 단어만 비슷하고 답이 없는 문서는 고르지 않는다.\n"
              "- 질문이 특정 기업의 사실(매출, 계약, 인력 등)을 묻는데 문서에 그 기업 이야기가 없으면 고르지 않는다.\n"
              "- 확실하지 않으면 고르지 않는다. 하나도 없으면 빈 목록을 돌려준다.\n\n"
              f"{listing}")
    picked = _llm().with_structured_output(Relevance).invoke(prompt).relevant
    return {"relevant": [s["docs"][i] for i in picked if 0 <= i < len(s["docs"])]}


def rewrite(s: RagState) -> RagState:
    prompt = (f"'{s['doc_type']}' 참고 문서에서 아래 질문의 답을 찾지 못했다.\n질문: {s['question']}\n"
              f"이미 써 본 검색어: {s.get('tried', [])}\n"
              "다른 표현 · 상위 개념 · 관련 제도 이름으로 새 검색어를 만든다. 한국어 하나, 영어 하나.")
    q = _llm().with_structured_output(Queries).invoke(prompt)
    return {"queries": [q.ko, q.en], "tried": s.get("tried", []) + [q.ko, q.en], "rewritten": True}


def after_grade(s: RagState) -> str:
    if s["relevant"] or s.get("rewritten"):
        return END                       # 찾았거나, 재작성 뒤에도 없으면 [] 로 끝낸다
    return "rewrite"


# ---------- 그래프 ----------

@lru_cache
def _graph():
    g = StateGraph(RagState)
    for name, fn in [("make_queries", make_queries), ("retrieve", retrieve),
                     ("grade", grade), ("rewrite", rewrite)]:
        g.add_node(name, fn)
    g.add_edge(START, "make_queries")
    g.add_edge("make_queries", "retrieve")
    g.add_edge("retrieve", "grade")
    g.add_conditional_edges("grade", after_grade, ["rewrite", END])
    g.add_edge("rewrite", "retrieve")
    return g.compile()


def to_hit(doc) -> RagHit:
    m = doc.metadata
    return {"chunk_id": f"{m['source']}#{m['id']}", "doc": m["title"], "page": m["page"],
            "text": doc.page_content, "score": m.get("score", 0.0)}


def rag_search(query: str, doc_type: DocType, k: int = 3,
               pipeline: list[dict] | None = None) -> list[RagHit]:
    """참고 문서에서 관련 청크를 찾는다. 관련 문서가 없으면 []."""
    if doc_type not in DOC_TYPES:
        raise ValueError(f"doc_type은 {DOC_TYPES} 중 하나")
    out = _graph().invoke({"question": query, "doc_type": doc_type, "pipeline": pipeline or [],
                           "k": k, "rewritten": False})
    return [to_hit(d) for d in out.get("relevant", [])]


def make_rag_tool(doc_type: DocType):
    """도구 호출(tool calling) 에이전트용. 예: tools=[make_rag_tool("regulation")]"""

    @tool(f"search_{doc_type}_docs")
    def _search(question: str) -> str:
        """참고 문서(가이드라인 · 보고서 · 통계)에서 판단 기준과 배경을 찾는다. 문서명과 쪽이 함께 나온다."""
        hits = rag_search(question, doc_type)
        if not hits:
            return "관련 근거를 찾지 못함"
        return "\n\n".join(f"[{h['doc']}, p.{h['page']}] {h['text'][:600]}" for h in hits)

    return _search
