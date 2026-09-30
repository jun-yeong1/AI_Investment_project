"""본문에서 실제 인용한 Evidence만 REFERENCE로 정리한다."""

from __future__ import annotations

from typing import Any


class CitationIndex:
    def __init__(self) -> None:
        self.entries: list[dict[str, Any]] = []
        self._numbers: dict[tuple[str, int | None], int] = {}

    def cite(self, evidence: dict) -> str:
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
                "evidence_ids": [],
            })
        ids = self.entries[number - 1]["evidence_ids"]
        if evidence.get("id") and evidence["id"] not in ids:
            ids.append(evidence["id"])
        return f"[{number}]"


def format_reference(entry: dict) -> str:
    """웹 URL 또는 문서명·쪽과 확인 가능한 날짜만 표시한다."""
    source = entry["source"]
    kind = "웹" if str(source).startswith(("http://", "https://")) else "문서"
    parts = [f"[{entry['number']}] {kind}: {source}"]
    if entry.get("page") is not None:
        parts.append(f"p.{entry['page']}")
    if entry.get("published"):
        parts.append(f"발행 {entry['published']}")
    if entry.get("accessed"):
        parts.append(f"열람 {entry['accessed']}")
    return " | ".join(parts)
