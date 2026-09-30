"""조사 노드가 공유하는 검색·원문 검증·근거 변환 로직."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Iterable, Literal, Mapping, Sequence

from dotenv import dotenv_values, load_dotenv
from pydantic import BaseModel, Field

from config import JUDGE_MODEL, JUDGE_PROVIDER, today
from state import State
from tools.evidence import Evidence, PipelineItem, make_evidence_id

LOGGER = logging.getLogger(__name__)


def _positive_int_setting(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        # .env를 프로세스 전역에 반영하지 않고 Agent 설정값만 읽는다.
        raw = dotenv_values(Path(__file__).resolve().parents[1] / ".env").get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name}은 양의 정수여야 합니다") from exc
    if value < 1:
        raise ValueError(f"{name}은 양의 정수여야 합니다")
    return value


MAX_URLS_PER_QUERY = _positive_int_setting("AGENT_URLS_PER_QUERY", 3)
MAX_PAGES_PER_NODE = _positive_int_setting("AGENT_PAGES_PER_NODE", 8)
MAX_PAGE_CHARS = _positive_int_setting("AGENT_PAGE_CHARS", 16000)
MAX_RAG_HIT_CHARS = _positive_int_setting("AGENT_RAG_HIT_CHARS", 2000)
PROMPT_DIR = Path(__file__).resolve().parents[1] / "prompts" / "research"


class Finding(BaseModel):
    item: str = Field(description="config.ITEMS의 평가 항목 코드")
    fact: str = Field(description="원문으로 확인할 수 있는 사실 한 줄")
    quote: str = Field(description="페이지 원문에 실제로 있는 짧은 인용문")
    status: Literal["확인됨", "기업 주장만"] = Field(
        description="독립 출처가 사실을 확인했으면 확인됨, 기업 발표를 전한 것뿐이면 기업 주장만"
    )


class PipelineFinding(BaseModel):
    substance: str
    indication: str
    stage: str
    quote: str = Field(description="목표 기업명과 물질명·적응증·단계의 연관성을 확인할 수 있는 페이지 원문 인용")


class PageAnalysis(BaseModel):
    findings: list[Finding] = Field(default_factory=list)
    pipeline: list[PipelineFinding] = Field(default_factory=list)


@dataclass(frozen=True)
class FetchedPage:
    url: str
    text: str
    published: str | None
    accessed: str


@dataclass(frozen=True)
class ResearchTools:
    """외부 도구 계약. 테스트에서는 가짜 함수를 주입한다.

    web_search(query) -> URL 문자열 목록 또는 URL을 가진 딕셔너리 목록
    fetch_page(url) -> {url, text, published, accessed} 또는 FetchedPage
    rag_search(query, doc_type, pipeline=...) -> 검색 결과; 기업 사실의 근거로 직접 쓰지 않는다.
    extract(...) -> 원문에서 구조화된 PageAnalysis
    """

    web_search: Callable[[str], Any]
    fetch_page: Callable[[str], Any]
    extract: Callable[[str, str, tuple[str, ...], FetchedPage, str], PageAnalysis]
    rag_search: Callable[..., Any] | None = None


def _normalize_space(value: str) -> str:
    return " ".join(value.split())


def _compact(value: str) -> str:
    """공백·문장부호를 무시하고 기업명과 물질명을 원문 인용과 대조한다."""
    return "".join(char for char in value.casefold() if char.isalnum())


def _urls(search_result: Any) -> Iterable[str]:
    # 검색 결과의 스니펫은 버리고 fetch_page에 전달할 URL만 취한다.
    if isinstance(search_result, Mapping):
        search_result = search_result.get("results", [])
    for hit in search_result or []:
        url = hit if isinstance(hit, str) else (
            hit.get("url") if isinstance(hit, Mapping) else getattr(hit, "url", None)
        )
        if isinstance(url, str) and url.startswith(("http://", "https://")):
            yield url


def _page(raw: Any, requested_url: str) -> FetchedPage:
    if isinstance(raw, FetchedPage):
        return raw
    if isinstance(raw, str):
        return FetchedPage(requested_url, raw, None, today())
    if isinstance(raw, Mapping):
        read = raw.get
    else:
        read = lambda key, default=None: getattr(raw, key, default)
    text = read("text")
    if not isinstance(text, str):
        raise ValueError("fetch_page() 결과에 text 문자열이 없습니다")
    return FetchedPage(
        url=str(read("url") or requested_url),
        text=text,
        published=read("published"),
        accessed=str(read("accessed") or today()),
    )


def _rag_context(results: Any) -> str:
    # 기준 문서의 청크는 추출 보조 문맥이며 기업별 Evidence로 변환하지 않는다.
    if isinstance(results, Mapping):
        results = results.get("hits", [])
    chunks: list[str] = []
    # 반환 개수(k)는 RAG 검색기가 정한다. 여기서 다시 상위 N개로 자르지 않는다.
    for hit in results or []:
        if isinstance(hit, Mapping):
            content = hit.get("text", "")
            source = hit.get("doc", hit.get("source", ""))
            page = hit.get("page", "")
        else:
            content = getattr(hit, "text", "")
            source = getattr(hit, "doc", getattr(hit, "source", ""))
            page = getattr(hit, "page", "")
        if content:
            chunks.append(f"[{source} p.{page}] {str(content)[:MAX_RAG_HIT_CHARS]}")
    return "\n".join(chunks)


@lru_cache(maxsize=1)
def _structured_llm():
    from langchain.chat_models import init_chat_model

    load_dotenv()
    model = os.getenv("AGENT_MODEL") or JUDGE_MODEL
    provider = os.getenv("AGENT_PROVIDER") or JUDGE_PROVIDER
    return init_chat_model(model, model_provider=provider, temperature=0).with_structured_output(PageAnalysis)


def extract_with_llm(
    area: str,
    company_name: str,
    allowed_items: tuple[str, ...],
    page: FetchedPage,
    rag_context: str,
) -> PageAnalysis:
    """검색 스니펫은 전달하지 않고 fetch_page 원문만 분석한다."""
    from langchain_core.messages import HumanMessage, SystemMessage

    instructions = (PROMPT_DIR / f"{area}.md").read_text(encoding="utf-8")
    rules = (
        f"{instructions}\n\n허용 항목 코드: {', '.join(allowed_items)}."
        " 목표 기업을 명시적으로 다루는 웹페이지 원문에서만 사실을 추출하세요."
        " quote는 원문에 실제로 있는 구절을 그대로 쓰세요."
        " 독립 기관의 확인·독립 보도가 아닌 기업 홈페이지·보도자료 및 이를 받아쓴 기사라면"
        " status를 '기업 주장만'으로 하세요. 정보가 없으면 추측하지 말고 빈 목록을 반환하세요."
        " 동일한 사실을 둘 이상의 항목에 넣지 마세요. RAG 참고자료는 기업 사실의 출처가 아닙니다."
    )
    material = (
        f"기업: {company_name}\n원문 URL: {page.url}\n발행일: {page.published or '미확인'}"
        f"\n판단 기준 참고자료:\n{rag_context or '없음'}"
        f"\n\n웹페이지 원문:\n{page.text[:MAX_PAGE_CHARS]}"
    )
    return _structured_llm().invoke([SystemMessage(content=rules), HumanMessage(content=material)])


def default_tools(*, with_rag: bool) -> ResearchTools:
    """웹·RAG 도구 import는 호출 시점까지 미룬다."""
    try:
        from tools.web import fetch_page, web_search
    except ImportError as exc:
        raise RuntimeError("tools/web.py를 불러올 수 없습니다. 테스트에는 ResearchTools를 주입하세요.") from exc

    rag_search = None
    if with_rag:
        try:
            from rag.rag_search import rag_search
        except ImportError as exc:
            raise RuntimeError("rag/rag_search.py를 불러올 수 없습니다. 테스트에는 ResearchTools를 주입하세요.") from exc
    return ResearchTools(web_search, fetch_page, extract_with_llm, rag_search)


def research(
    state: State,
    *,
    area: str,
    items: tuple[str, ...],
    queries: Sequence[str],
    rag_query: str | None,
    include_pipeline: bool,
    tools: ResearchTools | None,
) -> dict[str, Any]:
    """기업별 웹 원문을 근거로 조사하고 State 변경분만 돌려준다."""
    company = state.get("company")
    if not company or not company.get("company_id") or not company.get("name"):
        raise ValueError("조사 노드 실행 전에 company를 선택해야 합니다")
    services = tools or default_tools(with_rag=rag_query is not None)
    company_id, company_name = company["company_id"], company["name"]

    rag_context = ""
    web_fallback_queries: list[str] = []
    if rag_query is not None:
        if services.rag_search is None:
            raise ValueError(f"{area} 조사에는 rag_search가 필요합니다")
        # RAG가 국문·영문 질문 생성, 관련성 채점, 1회 재작성을 처리한다.
        rag_hits = services.rag_search(rag_query, area, pipeline=state.get("pipeline", []))
        if not rag_hits:
            # RAG의 재검색까지 실패하면 기업명과 함께 웹 원문을 보강한다.
            web_fallback_queries = [f"{company_name} {rag_query}"]
        # RAG에서 같은 청크를 여러 번 찾으면 참고 문맥에는 한 번만 싣는다.
        unique_hits: dict[str, Any] = {}
        for hit in rag_hits:
            key = hit.get("chunk_id") if isinstance(hit, Mapping) else getattr(hit, "chunk_id", None)
            key = str(key or (hit.get("text") if isinstance(hit, Mapping) else getattr(hit, "text", "")))
            unique_hits.setdefault(key, hit)
        rag_context = _rag_context(list(unique_hits.values()))

    evidence: list[Evidence] = []
    pipeline: list[PipelineItem] = []
    seen_urls: set[str] = set()
    pages_read = 0
    seen_quotes: set[tuple[str, str]] = set()
    seen_pipeline: set[tuple[str, str, str]] = set()
    item_counts = {item: 0 for item in items}

    # RAG가 실패한 항목의 웹 보강을 일반 기업 검색보다 먼저 수행한다.
    for query in (*web_fallback_queries, *queries):
        if pages_read >= MAX_PAGES_PER_NODE:
            break
        pages_for_query = 0
        for url in _urls(services.web_search(query)):
            if pages_for_query >= MAX_URLS_PER_QUERY or pages_read >= MAX_PAGES_PER_NODE:
                break
            if url in seen_urls:
                continue
            seen_urls.add(url)
            try:
                page = _page(services.fetch_page(url), url)
            except (ValueError, OSError) as exc:
                LOGGER.warning("원문 수집 실패: %s: %s", url, exc)
                continue
            if not page.text.strip():
                continue
            pages_read += 1
            pages_for_query += 1
            analysis = services.extract(area, company_name, items, page, rag_context)
            if not isinstance(analysis, PageAnalysis):
                analysis = PageAnalysis.model_validate(analysis)

            page_text = _normalize_space(page.text[:MAX_PAGE_CHARS])
            for finding in analysis.findings:
                quote = _normalize_space(finding.quote)
                quote_key = (page.url, quote)
                # 원문에 없는 인용과 동일 인용의 중복 채점을 막는다.
                if (
                    finding.item not in items
                    or not finding.fact.strip()
                    or not quote
                    or quote not in page_text
                    or quote_key in seen_quotes
                ):
                    continue
                seen_quotes.add(quote_key)
                item_counts[finding.item] += 1
                evidence.append(
                    Evidence(
                        id=make_evidence_id(company_id, finding.item, item_counts[finding.item]),
                        company_id=company_id,
                        item=finding.item,
                        fact=finding.fact.strip(),
                        quote=quote,
                        status=finding.status,
                        source=page.url,
                        page=None,
                        published=page.published,
                        accessed=page.accessed,
                    )
                )

            if include_pipeline:
                for found in analysis.pipeline:
                    key = (found.substance.strip(), found.indication.strip(), found.stage.strip())
                    quote = _normalize_space(found.quote)
                    compact_quote = _compact(quote)
                    # 여러 기업의 물질을 나열한 원문에서 다른 회사의 파이프라인을 가져오지 않는다.
                    if (
                        all(key)
                        and quote in page_text
                        and _compact(key[0]) in compact_quote
                        and any(_compact(alias) in compact_quote for alias in (company_name, company_id))
                        and key not in seen_pipeline
                    ):
                        seen_pipeline.add(key)
                        pipeline.append(PipelineItem(substance=key[0], indication=key[1], stage=key[2]))

    result: dict[str, Any] = {"evidence": evidence}
    if include_pipeline:
        result["pipeline"] = pipeline
    return result
