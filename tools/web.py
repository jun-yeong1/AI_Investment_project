"""웹 검색 URL과 페이지 원문을 수집한다. 검색 요약은 근거로 반환하지 않는다."""

from __future__ import annotations

import json
import os
import re
from datetime import date
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup
from dotenv import dotenv_values
from pypdf import PdfReader
from tavily import TavilyClient

ROOT = Path(__file__).resolve().parents[1]
USER_AGENT = "AI-Investment-Research/0.1"
TIMEOUT = (5, 20)
DATE_META_KEYS = {
    "article:published_time",
    "datepublished",
    "dc.date",
    "dc.date.issued",
    "citation_publication_date",
    "pubdate",
    "publishdate",
    "published",
}


@lru_cache(maxsize=1)
def _client() -> TavilyClient:
    key = os.getenv("TAVILY_API_KEY") or dotenv_values(ROOT / ".env").get("TAVILY_API_KEY")
    if not key:
        raise RuntimeError("TAVILY_API_KEY가 필요합니다")
    return TavilyClient(api_key=key)


def _http_url(url: str) -> str:
    parts = urlsplit(url.strip())
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        raise ValueError(f"HTTP(S) URL이 아닙니다: {url!r}")
    # 같은 문서의 앵커만 다른 검색 결과는 한 번만 수집한다.
    return urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, ""))


def web_search(query: str, max_results: int = 5) -> list[dict[str, str]]:
    """Tavily 검색 결과에서 URL과 제목만 반환한다."""
    if not query.strip():
        return []
    if max_results < 1:
        raise ValueError("max_results는 양수여야 합니다")
    response = _client().search(
        query=query,
        search_depth="basic",
        max_results=max_results,
        include_answer=False,
        include_raw_content=False,
    )
    results: list[dict[str, str]] = []
    seen: set[str] = set()
    for hit in response.get("results", []):
        try:
            url = _http_url(hit["url"])
        except (KeyError, TypeError, ValueError):
            continue
        if url in seen:
            continue
        seen.add(url)
        results.append({"url": url, "title": str(hit.get("title") or "")})
    return results


def _parse_date(value: str | None) -> str | None:
    if not value:
        return None
    match = re.search(
        r"(?<!\d)(\d{4})\s*[-./년]\s*(\d{1,2})\s*[-./월]\s*(\d{1,2})",
        value,
    )
    if not match:
        return None
    try:
        return date(*(int(part) for part in match.groups())).isoformat()
    except ValueError:
        return None


def _json_dates(value: Any):
    if isinstance(value, dict):
        for key in ("datePublished", "dateCreated", "dateModified"):
            if key in value:
                yield str(value[key])
        for child in value.values():
            yield from _json_dates(child)
    elif isinstance(value, list):
        for child in value:
            yield from _json_dates(child)


def _published_date(soup: BeautifulSoup) -> str | None:
    for meta in soup.find_all("meta"):
        key = str(meta.get("property") or meta.get("name") or "").lower()
        if key in DATE_META_KEYS:
            parsed = _parse_date(meta.get("content"))
            if parsed:
                return parsed
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or script.get_text())
        except (TypeError, ValueError):
            continue
        for value in _json_dates(data):
            parsed = _parse_date(value)
            if parsed:
                return parsed
    for tag in soup.find_all("time"):
        parsed = _parse_date(tag.get("datetime") or tag.get_text(" ", strip=True))
        if parsed:
            return parsed
    return None


def _html_text(content: bytes) -> tuple[str, str | None]:
    soup = BeautifulSoup(content, "html.parser")
    published = _published_date(soup)
    for element in soup(["script", "style", "noscript", "nav", "footer", "aside", "form"]):
        element.decompose()
    body = soup.find("article") or soup.find("main") or soup.body or soup
    lines = [" ".join(line.split()) for line in body.get_text("\n", strip=True).splitlines()]
    text = "\n".join(line for line in lines if line)
    return text, published


def _pdf_text(content: bytes) -> str:
    reader = PdfReader(BytesIO(content))
    pages = []
    for number, page in enumerate(reader.pages, start=1):
        body = page.extract_text() or ""
        if body.strip():
            pages.append(f"[PDF {number}쪽]\n{body.strip()}")
    return "\n\n".join(pages)


def fetch_page(url: str) -> dict[str, str | None]:
    """URL의 HTML 또는 텍스트 PDF 원문을 열고 출처 날짜를 반환한다."""
    requested_url = _http_url(url)
    response = requests.get(
        requested_url,
        headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/pdf;q=0.9,*/*;q=0.8"},
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    final_url = _http_url(response.url or requested_url)
    content_type = response.headers.get("Content-Type", "").lower()
    if (
        "application/pdf" in content_type
        or urlsplit(final_url).path.lower().endswith(".pdf")
        or response.content.lstrip().startswith(b"%PDF-")
    ):
        text, published = _pdf_text(response.content), None
    else:
        text, published = _html_text(response.content)
    if not text.strip():
        raise ValueError(f"원문 텍스트를 추출하지 못했습니다: {final_url}")
    return {
        "url": final_url,
        "text": text,
        "published": published,
        "accessed": date.today().isoformat(),
    }
