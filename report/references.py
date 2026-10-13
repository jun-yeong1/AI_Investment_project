"""본문에서 실제 인용한 Evidence만 REFERENCE로 정리한다."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

# co.kr처럼 국가 도메인 앞에 붙는 접미는 한 덩어리로 본다.
SECOND_LEVELS = {"co", "or", "go", "ne", "re", "pe", "ac", "com", "net", "org", "gov", "edu"}


def is_web(source: str) -> bool:
    return str(source).startswith(("http://", "https://"))


def domain_of(source: str) -> str:
    """URL이면 www·m 같은 하위 도메인을 뺀 도메인, 문서명이면 그대로 돌려준다."""
    source = str(source).strip()
    try:
        host = (urlsplit(source).hostname or "") if is_web(source) else ""
    except ValueError:
        host = ""
    labels = host.lower().split(".") if host else []
    if len(labels) < 2:
        return host.lower() or source
    keep = 3 if len(labels) >= 3 and len(labels[-1]) == 2 and labels[-2] in SECOND_LEVELS else 2
    return ".".join(labels[-keep:])


class CitationIndex:
    def __init__(self) -> None:
        self.entries: list[dict[str, Any]] = []
        self._numbers: dict[tuple[str, int | None], int] = {}

    def add(self, evidence: dict) -> int:
        """근거의 출처를 등록하고 REFERENCE 번호를 돌려준다. 같은 출처·쪽은 같은 번호다."""
        source = str(evidence.get("source") or "").strip()
        if not source:
            raise ValueError(f"근거 {evidence.get('id', '(ID 없음)')}에 출처가 없습니다")
        page = evidence.get("page")
        key = (source, page)
        number = self._numbers.get(key)
        if number is None:
            number = len(self.entries) + 1
            self._numbers[key] = number
            self.entries.append({
                "number": number,
                "source": source,
                "page": page,
                "published": evidence.get("published"),
                "accessed": evidence.get("accessed"),
                "title": evidence.get("title"),
                "evidence_ids": [],
            })
        entry = self.entries[number - 1]
        # 같은 출처의 다른 근거에 제목·발행일이 있으면 빈칸을 채운다.
        for field in ("title", "published"):
            if not entry[field] and evidence.get(field):
                entry[field] = evidence[field]
        if evidence.get("id") and evidence["id"] not in entry["evidence_ids"]:
            entry["evidence_ids"].append(evidence["id"])
        return number

    def cite(self, evidence: dict) -> str:
        return f"[{self.add(evidence)}]"


def format_reference(entry: dict) -> str:
    """웹페이지는 '작성 사이트(날짜). 제목. 사이트명, URL'로 쓴다. 작성자를 모르니 도메인을 쓴다."""
    source = str(entry["source"])
    site = domain_of(source)
    published = entry.get("published") or "n.d."
    accessed = f" 열람 {entry['accessed']}." if not entry.get("published") and entry.get("accessed") else ""
    title = " ".join(str(entry.get("title") or "").split()).rstrip(".")
    parts = [f"[{entry['number']}] {site}({published})."]
    if title:
        parts.append(f"{title}.")
    location = f"{site}, {source}" if is_web(source) else ""
    if entry.get("page") is not None:
        page = f"p.{entry['page']}"
        location = f"{location}, {page}" if location else page
    if location:
        parts.append(location)
    return " ".join(parts) + accessed
