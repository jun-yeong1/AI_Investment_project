"""SUMMARY, 1~5장, REFERENCE 순서의 한국어 PDF를 흐르는 레이아웃으로 만든다. 최대 10쪽."""

from __future__ import annotations

import unicodedata
from datetime import date
from pathlib import Path
from typing import Iterable

import pymupdf

from report.references import format_reference

PAGE_W, PAGE_H = pymupdf.paper_size("a4")
MARGIN = 43
BOTTOM = PAGE_H - 45
MAX_PAGES = 10
BODY_SIZE = 9.4
TABLE_SIZE = 8.8
TABLE_HEADER = ("기업", "합계", "판정", "환산 점수 (/100)")
TABLE_WIDTHS = (111, 48, 101, PAGE_W - 2 * MARGIN - 260)
INK = (0.12, 0.19, 0.28)
MUTED = (0.38, 0.44, 0.50)
ACCENT = (0.13, 0.37, 0.56)
LIGHT = (0.94, 0.97, 0.99)
FONT_PATH = next((path for path in (
    Path("/System/Library/Fonts/Supplemental/AppleGothic.ttf"),
    Path("/Library/Fonts/AppleGothic.ttf"),
) if path.is_file()), None)
FONT_NAME = "report_korean" if FONT_PATH else "korea"
FONT = pymupdf.Font(fontfile=str(FONT_PATH)) if FONT_PATH else None


def _text_width(value: str, size: float) -> float:
    if FONT is not None:
        return FONT.text_length(value, fontsize=size)
    # 내장 CJK 폰트는 Font.text_length가 실제 insert_text 폭보다 작게 계산된다.
    return pymupdf.get_text_length(value, fontname=FONT_NAME, fontsize=size)


GLYPH_FALLBACK = {"‧": "·", "®": "(R)"}


def _printable(word: str) -> str:
    """글꼴에 없는 글자는 빈 칸으로 찍히므로 같은 뜻의 글자로 바꾼다(마이크로 기호 µ -> 그리스 문자 μ 등)."""
    if FONT is None:
        return word

    def swap(char: str) -> str:
        if FONT.has_glyph(ord(char)):
            return char
        alt = GLYPH_FALLBACK.get(char) or unicodedata.normalize("NFKC", char)
        return alt if all(FONT.has_glyph(ord(c)) for c in alt) else "?"

    return "".join(swap(char) for char in word)


def _wrap(text: str, width: float, size: float) -> list[str]:
    """한글 문장과 공백 없는 URL을 모두 페이지 폭 안에서 줄바꿈한다."""
    words = [_printable(word) for word in str(text).split()]
    if not words:
        return [""]
    lines: list[str] = []
    line = ""
    for word in words:
        trial = f"{line} {word}" if line else word
        if _text_width(trial, size) <= width:
            line = trial
            continue
        if line:
            lines.append(line)
            line = ""
        # URL처럼 공백 없이 긴 단어는 글자 단위로 끊는다.
        for char in word:
            if _text_width(line + char, size) > width and line:
                lines.append(line)
                line = ""
            line += char
    if line:
        lines.append(line)
    return lines


def _reference_style(count: int) -> tuple[float, float, float]:
    """출처가 많을수록 글자를 줄여 REFERENCE가 쪽수를 덜 차지하게 한다. (크기, 줄 간격, 항목 간격)"""
    if count <= 12:
        return 8.4, 12.2, 5
    if count <= 24:
        return 7.8, 11.2, 4
    return 7.2, 10.2, 3


class _Report:
    def __init__(self, title: str):
        self.doc = pymupdf.open()
        self.title = title
        self._new_page()

    def _new_page(self) -> None:
        self.page = self.doc.new_page(width=PAGE_W, height=PAGE_H)
        if FONT_PATH:
            self.page.insert_font(fontname=FONT_NAME, fontfile=str(FONT_PATH))
        self.page.draw_rect(pymupdf.Rect(0, 0, PAGE_W, 9), color=ACCENT, fill=ACCENT)
        self.y = 47.0
        self._draw([self.title], size=14, color=INK, leading=14 * 1.55)
        self.y += 9
        self.page.draw_line((MARGIN, self.y), (PAGE_W - MARGIN, self.y), color=ACCENT, width=0.8)
        self.y += 13
        self.body_top = self.y
        self.page.draw_line((MARGIN, PAGE_H - 36), (PAGE_W - MARGIN, PAGE_H - 36),
                            color=(0.80, 0.84, 0.88), width=0.5)
        self.page.insert_text((MARGIN, PAGE_H - 21), date.today().isoformat(),
                              fontsize=8, fontname=FONT_NAME, color=MUTED)

    def _ensure(self, height: float) -> None:
        if self.y + height > BOTTOM:
            self._new_page()

    def _draw(self, lines: list[str], *, size: float, color, leading: float, indent: float = 0) -> None:
        for line in lines:
            self.page.insert_text((MARGIN + indent, self.y + size), line,
                                  fontsize=size, fontname=FONT_NAME, color=color)
            self.y += leading

    def text(self, value: str, *, size: float = BODY_SIZE, color=INK, gap: float = 5,
             indent: float = 0, leading: float | None = None) -> None:
        leading = leading or size * 1.55
        lines = _wrap(value, PAGE_W - 2 * MARGIN - indent, size)
        if len(lines) * leading + gap <= BOTTOM - self.body_top:
            # 문단은 쪽 사이에서 끊지 않고 통째로 다음 쪽으로 넘긴다.
            self._ensure(len(lines) * leading + gap)
            self._draw(lines, size=size, color=color, leading=leading, indent=indent)
        else:
            for line in lines:
                self._ensure(leading)
                self._draw([line], size=size, color=color, leading=leading, indent=indent)
        self.y += gap

    def heading(self, label: str, keep: float = 40) -> None:
        # 제목만 쪽 끝에 남지 않게 뒤따르는 내용(기본은 두어 줄, 표가 오면 표 전체)을 같이 확인한다.
        self._ensure(8 + 17 + 11 + keep)
        self.y += 8
        self.text(label, size=12, color=ACCENT, gap=11, leading=17)

    def bullets(self, lines: Iterable[str], *, size: float = BODY_SIZE) -> None:
        for line in lines:
            self.text("• " + line, size=size, gap=5, indent=2)

    def table(self, cells: list[tuple[list[list[str]], float]]) -> None:
        # 표는 쪽 사이에서 쪼개지 않는다.
        self._ensure(sum(height for _, height in cells))
        for index, (cell_lines, height) in enumerate(cells):
            if index == 0:
                fill, foreground = ACCENT, (1, 1, 1)
            else:
                fill, foreground = (LIGHT if index % 2 == 1 else (1, 1, 1)), INK
            self._row(cell_lines, height, fill=fill, foreground=foreground, size=TABLE_SIZE)
        self.y += 13

    def _row(self, cell_lines: list[list[str]], height: float, *, fill, foreground, size: float) -> None:
        self.page.draw_rect(pymupdf.Rect(MARGIN, self.y, PAGE_W - MARGIN, self.y + height),
                            color=(0.83, 0.87, 0.90), fill=fill, width=0.4)
        x = MARGIN
        for lines, width in zip(cell_lines, TABLE_WIDTHS):
            for index, line in enumerate(lines):
                self.page.insert_text((x + 5, self.y + 5 + size + index * 13), line,
                                      fontsize=size, fontname=FONT_NAME, color=foreground)
            x += width
        self.y += height

    def references(self, entries: list[dict]) -> None:
        if not entries:
            self.text("본문에서 개별 외부 자료를 직접 인용하지 않음.", size=9.1)
            return
        size, leading, gap = _reference_style(len(entries))
        for entry in entries:
            self.text(format_reference(entry), size=size, gap=gap, leading=leading)

    def save(self, destination: Path, strict: bool = True) -> int:
        total = len(self.doc)
        if strict and total > MAX_PAGES:
            raise ValueError(f"보고서가 {total}쪽으로 최대 {MAX_PAGES}쪽을 넘었습니다. 인용·문장을 줄여야 합니다")
        for number, page in enumerate(self.doc, start=1):
            label = f"{number} / {total}"
            page.insert_text((PAGE_W - MARGIN - _text_width(label, 8), PAGE_H - 21), label,
                             fontsize=8, fontname=FONT_NAME, color=MUTED)
        self.doc.set_metadata({"title": self.title, "author": "AI Investment Project"})
        self.doc.subset_fonts()  # 한글 글꼴 전체(약 6MB) 대신 쓴 글자만 넣는다
        self.doc.save(destination, garbage=4, deflate=True)
        return total


def _signed(score) -> str:
    return f"{score:+d}" if isinstance(score, int) else str(score)


def _table_cells(rows: list[dict]) -> list[tuple[list[list[str]], float]]:
    """표의 줄마다 (칸별 줄바꿈 결과, 높이). 머리글 줄이 맨 앞에 온다."""
    body = [(str(row["item"]), _signed(row["score"]), str(row["status"]), str(row["citation"]))
            for row in rows]
    cells = []
    for values in (TABLE_HEADER, *body):
        cell_lines = [_wrap(value, width - 10, TABLE_SIZE) for value, width in zip(values, TABLE_WIDTHS)]
        cells.append((cell_lines, max(23, max(len(lines) for lines in cell_lines) * 13 + 8)))
    return cells


def render_report(sections: dict, path: str | Path, *, strict: bool = True) -> int:
    """통합 보고서를 PDF로 저장하고 쪽수를 돌려준다. strict면 10쪽을 넘을 때 저장하지 않고 ValueError."""
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    report = _Report(sections["title"])
    try:
        report.heading("SUMMARY")
        summary = [line["text"] for line in sections.get("summary", [])]
        if summary:
            report.text(summary[0], size=13, color=ACCENT, gap=11)
            report.bullets(summary[1:])
        for chapter in sections["chapters"]:
            cells = _table_cells(chapter["table"]) if chapter.get("table") else []
            report.heading(chapter["title"], keep=sum(height for _, height in cells) or 40)
            if cells:
                report.table(cells)
            report.bullets(line["text"] for line in chapter["lines"])
        report.heading("REFERENCE")
        report.references(sections.get("references", []))
        return report.save(destination, strict)
    finally:
        report.doc.close()
