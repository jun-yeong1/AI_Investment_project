"""Agentic RAG 검색 — 에이전트는 rag_search() 하나만 부르면 된다.

    from rag.rag_search import rag_search
    evidence = rag_search(
        "희귀의약품 지정이 신약 개발 위험에서 어떤 의미인가",
        doc_type="규제",                       # 규제 | 기술 | 시장·사업성
        company="닥터노아바이오텍",
        pipeline=[{"name": "NDC-011", "indication": "ALS", "stage": "전임상"}],
    )
    # → list[Evidence] (tools/evidence.py). RAG 근거는 status="확인됨", 웹 근거는 "미분류"

흐름 (설계서 B-2 "RAG 에이전트 내부 흐름")
    질문 생성(한국어 + 영어) → 하이브리드 검색 → 관련성 채점
        ├ 관련 있음            → 근거 기록
        ├ 관련 없음, 재작성 전 → 질문 다시 쓰기 → 다시 검색
        └ 관련 없음, 재작성 후 → 웹 검색 보강

RAG 문서에는 특정 기업 이야기가 없고 기준 · 제도 · 통계가 들어 있다.
그래서 검색 질문은 기업 이름 대신 일반 개념(제도 이름, 적응증, 개발 단계)으로 바꿔서 만든다.

환경변수 (.env)
    OPENAI_API_KEY   필수 — 질문 생성 · 관련성 채점
    TAVILY_API_KEY   선택 — 웹 보강 (없으면 웹 단계를 건너뛴다)
    RAG_LLM_MODEL    기본 gpt-4o-mini
    RAG_SEARCH_MODE  기본 ensemble (임베딩 인덱스가 없으면 bm25)
"""
import os
from functools import lru_cache
from typing import TypedDict

from dotenv import load_dotenv
from langchain.chat_models import init_chat_model
from langchain_core.tools import tool
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from rag.retriever import get_retriever
from rag.sources import DOC_TYPES
from tools.evidence import Evidence, make_evidence

load_dotenv()
LLM_MODEL = os.getenv("RAG_LLM_MODEL", "gpt-4o-mini")
SEARCH_MODE = os.getenv("RAG_SEARCH_MODE", "ensemble")
TOOL_NAMES = {"규제": "regulation", "기술": "technology", "시장·사업성": "market"}


class Queries(BaseModel):
    ko: str = Field(description="한국어 검색 질문")
    en: str = Field(description="English search query")


class Relevance(BaseModel):
    relevant: list[int] = Field(description="질문에 답하는 데 실제로 쓸 수 있는 문서 번호. 없으면 빈 목록")


class RagState(TypedDict, total=False):
    question: str
    doc_type: str
    company: str
    pipeline: list[dict]
    k: int
    queries: list[str]
    tried: list[str]          # 이미 써 본 질문 — 재작성 때 반복하지 않게
    docs: list
    relevant: list
    rewritten: bool
    evidence: list[Evidence]


@lru_cache
def _llm():
    return init_chat_model(LLM_MODEL, temperature=0)


def _pipeline_text(pipeline: list[dict]) -> str:
    if not pipeline:
        return "없음"
    return ", ".join(f"{p.get('name', '?')}({p.get('indication', '?')}, {p.get('stage', '?')})" for p in pipeline)


# ---------- 노드 ----------

def make_queries(s: RagState) -> RagState:
    prompt = (
        f"'{s['doc_type']}' 참고 문서(가이드라인 · 보고서 · 통계)를 검색할 질문을 만든다.\n"
        f"원래 질문: {s['question']}\n"
        f"평가 중인 기업: {s.get('company') or '없음'} / 파이프라인: {_pipeline_text(s.get('pipeline', []))}\n"
        "문서에는 특정 기업 이야기가 없으므로 기업 이름은 빼고, 제도 이름 · 적응증 · 개발 단계 같은 "
        "일반 개념으로 바꿔라. 한국어 질문 하나와 영어 질문 하나를 만든다."
    )
    q = _llm().with_structured_output(Queries).invoke(prompt)
    return {"queries": [q.ko, q.en], "tried": [q.ko, q.en]}


def retrieve(s: RagState) -> RagState:
    k = s.get("k", 3)
    retriever = get_retriever(s["doc_type"], k=k, mode=SEARCH_MODE)
    results = [retriever.invoke(q)[:k] for q in s["queries"]]
    merged, seen = [], set()
    for rank in range(k):                       # 한국어 · 영어 결과를 번갈아 합친다
        for docs in results:
            if rank < len(docs) and docs[rank].metadata["id"] not in seen:
                seen.add(docs[rank].metadata["id"])
                merged.append(docs[rank])
    return {"docs": merged}


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


def web(s: RagState) -> RagState:
    company = s.get("company", "")
    results = _web_search(f"{s['question']} {company}".strip(), k=s.get("k", 3) + 2)
    if company:   # 다른 회사 기사가 섞이지 않게, 기업 이름이 나오는 결과만 남긴다
        results = [r for r in results if company in r["title"] + r["content"]]
    results = results[: s.get("k", 3)]
    return {"evidence": [make_evidence(
        company=s.get("company", ""), fact=r["content"][:150], quote=r["content"], status="미분류",
        source_type="web", title=r["title"], url=r["url"], published=r.get("published", ""),
    ) for r in results]}


def record(s: RagState) -> RagState:
    return {"evidence": [make_evidence(
        company=s.get("company", ""), fact=d.page_content[:150], quote=d.page_content, status="확인됨",
        source_type="rag", doc_type=d.metadata["doc_type"], title=d.metadata["title"],
        publisher=d.metadata["publisher"], url=d.metadata["source_url"], page=d.metadata["page"],
        published=str(d.metadata["year"]),
    ) for d in s["relevant"]]}


def after_grade(s: RagState) -> str:
    if s["relevant"]:
        return "record"
    return "web" if s.get("rewritten") else "rewrite"


def _web_search(query: str, k: int = 3) -> list[dict]:
    """에이전트 팀의 tools.web.web_search가 있으면 그걸 쓰고, 없으면 Tavily를 직접 쓴다.
    반환 형식: [{"title", "url", "content"(본문 발췌), "published"}]"""
    try:
        from tools.web import web_search
        return web_search(query, k=k)
    except ImportError:
        pass
    if not os.getenv("TAVILY_API_KEY"):
        return []
    from langchain_tavily import TavilySearch
    res = TavilySearch(max_results=k, include_raw_content=True).invoke({"query": query})
    return [{"title": r.get("title", ""), "url": r["url"],
             "content": (r.get("raw_content") or r.get("content") or "")[:1500],
             "published": r.get("published_date", "")} for r in res.get("results", [])]


# ---------- 그래프 ----------

@lru_cache
def _graph():
    g = StateGraph(RagState)
    for name, fn in [("make_queries", make_queries), ("retrieve", retrieve), ("grade", grade),
                     ("rewrite", rewrite), ("web", web), ("record", record)]:
        g.add_node(name, fn)
    g.add_edge(START, "make_queries")
    g.add_edge("make_queries", "retrieve")
    g.add_edge("retrieve", "grade")
    g.add_conditional_edges("grade", after_grade, ["record", "rewrite", "web"])
    g.add_edge("rewrite", "retrieve")
    g.add_edge("record", END)
    g.add_edge("web", END)
    return g.compile()


def rag_search(question: str, doc_type: str, company: str = "",
               pipeline: list[dict] | None = None, k: int = 3) -> list[Evidence]:
    """참고 문서에서 근거를 찾아 Evidence 목록으로 돌려준다."""
    if doc_type not in DOC_TYPES:
        raise ValueError(f"doc_type은 {DOC_TYPES} 중 하나")
    out = _graph().invoke({"question": question, "doc_type": doc_type, "company": company,
                           "pipeline": pipeline or [], "k": k, "rewritten": False})
    return out.get("evidence", [])


def make_rag_tool(doc_type: str, company: str = ""):
    """도구 호출(tool calling) 에이전트용. 예: tools=[make_rag_tool("규제", company)]"""

    @tool(f"search_{TOOL_NAMES[doc_type]}_docs")
    def _search(question: str) -> str:
        """참고 문서(가이드라인 · 보고서 · 통계)에서 판단 기준과 배경을 찾는다. 출처와 쪽이 함께 나온다."""
        evs = rag_search(question, doc_type, company)
        if not evs:
            return "관련 근거를 찾지 못함"
        return "\n\n".join(f"[{e['title']}, p.{e.get('page')}] {e['quote'][:600]}" for e in evs)

    return _search
