"""E절 순서의 한국어 PDF를 만들고 기업별 PDF를 평가 순서대로 합친다."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Iterable

import pymupdf

from report.references import format_reference

ROOT = Path(__file__).resolve().parents[1]
PAGE_W, PAGE_H = pymupdf.paper_size("a4")
MARGIN = 43
BOTTOM = PAGE_H - 45
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


def _wrap(text: str, width: float, size: float) -> list[str]:
    """한글 문장과 공백 없는 URL을 모두 페이지 폭 안에서 줄바꿈한다."""
    words = str(text).split()
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


class _Page:
    def __init__(self, doc: pymupdf.Document, title: str, page_number: int, section: str):
        self.page = doc.new_page(width=PAGE_W, height=PAGE_H)
        if FONT_PATH:
            self.page.insert_font(fontname=FONT_NAME, fontfile=str(FONT_PATH))
        self.y = 47.0
        self.page.draw_rect(pymupdf.Rect(0, 0, PAGE_W, 9), color=ACCENT, fill=ACCENT)
        self.text(title, size=14, color=INK, gap=9)
        self.page.draw_line((MARGIN, self.y), (PAGE_W - MARGIN, self.y), color=ACCENT, width=0.8)
        self.y += 13
        self.heading(section)
        self.page.draw_line((MARGIN, PAGE_H - 36), (PAGE_W - MARGIN, PAGE_H - 36),
                            color=(0.80, 0.84, 0.88), width=0.5)
        self.page.insert_text((MARGIN, PAGE_H - 21), date.today().isoformat(),
                              fontsize=8, fontname=FONT_NAME, color=MUTED)
        self.page.insert_text((PAGE_W - MARGIN - 37, PAGE_H - 21), f"{page_number} / 5",
                              fontsize=8, fontname=FONT_NAME, color=MUTED)

    def _reserve(self, height: float) -> None:
        if self.y + height > BOTTOM:
            raise ValueError("보고서 본문이 5쪽 지정 영역을 넘었습니다. 인용·문장을 줄여야 합니다")

    def text(self, value: str, *, size: float = 9.5, color=INK, gap: float = 5,
             indent: float = 0, leading: float | None = None) -> None:
        leading = leading or size * 1.55
        lines = _wrap(value, PAGE_W - 2 * MARGIN - indent, size)
        self._reserve(len(lines) * leading + gap)
        for line in lines:
            self.page.insert_text((MARGIN + indent, self.y + size), line,
                                  fontsize=size, fontname=FONT_NAME, color=color)
            self.y += leading
        self.y += gap

    def heading(self, label: str) -> None:
        self.y += 8
        self.text(label, size=12, color=ACCENT, gap=11, leading=17)

    def bullets(self, lines: Iterable[str], *, size: float = 9.5) -> None:
        for line in lines:
            self.text("• " + line, size=size, gap=5, indent=2)

    def table(self, rows: list[dict]) -> None:
        widths = (111, 48, 101, PAGE_W - 2 * MARGIN - 260)
        columns = ("항목 / 기업", "점수", "근거 상태 / 판정", "대표 인용 / 환산")
        self._row(columns, widths, fill=ACCENT, foreground=(1, 1, 1), size=8.8)
        for index, row in enumerate(rows):
            values = (str(row["item"]), f"{row['score']:+d}", str(row["status"]), str(row["citation"]))
            self._row(values, widths, fill=LIGHT if index % 2 == 0 else (1, 1, 1),
                      foreground=INK, size=8.7)
        self.y += 13

    def _row(self, values: tuple[str, ...], widths: tuple[float, ...], *, fill, foreground,
             size: float) -> None:
        cell_lines = [_wrap(value, width - 10, size) for value, width in zip(values, widths)]
        height = max(23, max(len(lines) for lines in cell_lines) * 13 + 8)
        self._reserve(height)
        self.page.draw_rect(pymupdf.Rect(MARGIN, self.y, PAGE_W - MARGIN, self.y + height),
                            color=(0.83, 0.87, 0.90), fill=fill, width=0.4)
        x = MARGIN
        for lines, width in zip(cell_lines, widths):
            for index, line in enumerate(lines):
                self.page.insert_text((x + 5, self.y + 5 + size + index * 13), line,
                                      fontsize=size, fontname=FONT_NAME, color=foreground)
            x += width
        self.y += height


def render_report(sections: dict, path: str | Path) -> Path:
    """SUMMARY, 1~5장, REFERENCE 순서로 최대 5쪽 PDF를 저장한다."""
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    doc = pymupdf.open()
    try:
        first = _Page(doc, sections["title"], 1, "SUMMARY")
        summary = sections["summary"]
        first.text(summary[0], size=14, color=ACCENT, gap=13)
        first.bullets(summary[1:], size=9.4)
        first.heading("1. 기업 개요와 팀")
        first.bullets(sections["chapter1"])

        second = _Page(doc, sections["title"], 2, "2. 시장 · 경쟁 리스크")
        second.bullets(sections["chapter2"])

        third = _Page(doc, sections["title"], 3, "3. 기술 · 규제 리스크")
        third.bullets(sections["chapter3"])

        fourth = _Page(doc, sections["title"], 4, "4. 리스크 종합과 투자 판단")
        fourth.table(sections["chapter4"]["rows"])
        fourth.bullets(sections["chapter4"]["notes"], size=9.1)

        fifth = _Page(doc, sections["title"], 5, "5. 한계점")
        fifth.bullets(sections["chapter5"], size=9.1)
        fifth.heading("REFERENCE")
        if sections["references"]:
            count = len(sections["references"])
            ref_size, ref_leading, ref_gap = (
                (8.4, 12.2, 5) if count <= 6 else
                (7.5, 10.4, 3) if count <= 10 else
                (6.8, 9.0, 2)
            )
            for entry in sections["references"]:
                fifth.text(format_reference(entry), size=ref_size, gap=ref_gap,
                           leading=ref_leading)
        else:
            fifth.text("본문에서 개별 외부 자료를 직접 인용하지 않음.", size=9.1)

        doc.set_metadata({"title": sections["title"], "author": "AI Investment Project"})
        doc.save(destination, garbage=4, deflate=True)
    finally:
        doc.close()
    return destination


def merge_reports(paths: Iterable[str | Path], output: str | Path | None = None) -> Path:
    """그래프의 reports 누적 순서(후보 평가 순서) 그대로 하나의 PDF로 합친다."""
    inputs = [Path(path) for path in paths]
    if not inputs:
        raise ValueError("병합할 보고서가 없습니다")
    if any(not path.is_file() for path in inputs):
        raise FileNotFoundError("병합 대상 보고서가 없습니다")
    destination = Path(output) if output else ROOT / "outputs" / "investment_reports.pdf"
    if destination.resolve() in {path.resolve() for path in inputs}:
        raise ValueError("병합 결과 파일은 원본 보고서와 다른 경로여야 합니다")
    destination.parent.mkdir(parents=True, exist_ok=True)
    merged = pymupdf.open()
    try:
        for path in inputs:
            with pymupdf.open(path) as source:
                merged.insert_pdf(source)
        merged.set_metadata({"title": "AI 신약개발 스타트업 투자 심사 보고서"})
        merged.save(destination, garbage=4, deflate=True)
    finally:
        merged.close()
    return destination


def finalize_reports(state: dict, output: str | Path | None = None) -> Path:
    """전체 그래프 종료 후 app.py가 호출할 최종 병합 함수."""
    return merge_reports(state.get("reports", []), output)
