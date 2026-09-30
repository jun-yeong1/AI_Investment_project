"""RAG 문서 파싱: PDF → 정제한 텍스트 → 청크 → data/processed/chunks.jsonl

실행: python -m rag.parse_pdfs [--chunk-size 1000]   (저장소 루트에서)
필요: pip install pymupdf langchain-text-splitters langchain-core

흐름
  1. 쪽 단위로 텍스트 추출 (PyMuPDF) — 쪽 번호를 메타데이터로 남겨 인용에 쓴다
  2. 정제 — 문서마다 섞여 나오는 잡음 제거
     - 여러 쪽에 반복되는 머리말·꼬리말 (FDA 가이드 머리말, BIO 저작권 줄)
     - 숫자만 있는 줄 (줄번호, 쪽번호 "- 7 -", BIO 표 조각)
     - 글자가 거의 없는 쪽 (KISTEP 1쪽 이미지 표지)
     - 문장 중간에서 끊긴 줄바꿈은 이어 붙이고, 글머리(□ ❍ ㅇ * -)는 새 줄로 유지
     - 영문 합자(ﬁ → fi)를 풀어 키워드 검색이 맞게 함
  3. 청크 분할 (기본 1000자 / 겹침은 청크 크기의 10%, 문자 기준)
  4. data/processed/chunks_{크기}.jsonl 저장 — 사람이 열어 보고 청크 품질을 확인할 수 있게
"""
import argparse
import json
import re
from collections import Counter
from pathlib import Path

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from rag.sources import DOCS, doc_meta

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw"
OUT_DIR = ROOT / "data" / "processed"

MIN_PAGE_CHARS = 50                          # 이보다 짧은 쪽은 표지·빈 쪽으로 보고 건너뜀
REPEAT_RATIO = 0.3                           # 전체 쪽의 30% 이상에 나오는 줄 = 머리말·꼬리말
NUMERIC_LINE = re.compile(r"^[\d\s.,%/\-–—()]*$|^- ?\d+ ?-$|^\d+/ ?\w+ \d{4}$")
BULLET_START = re.compile(r"^(□|❍|○|ㅇ|◦|•|·|\*|-|–|➡|√|※|\d+\.|[가-하]\.|[IVX]+\.|[A-Z]\.)\s?")
SENTENCE_END = re.compile(r"[.!?。:;)]$|다\.?$|음\.?$|함\.?$")
# 영문 PDF의 합자(ﬁ ﬂ 등)를 풀어야 "first" 같은 검색어가 BM25에서 맞는다
LIGATURES = str.maketrans({"ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi", "ﬄ": "ffl", "ﬅ": "st", "ﬆ": "st"})


def repeated_lines(pages: list[str]) -> set[str]:
    """여러 쪽에 똑같이 나오는 줄(머리말·꼬리말)을 찾는다."""
    counter = Counter()
    for text in pages:
        counter.update({line.strip() for line in text.splitlines() if line.strip()})
    threshold = max(3, int(len(pages) * REPEAT_RATIO))
    return {line for line, n in counter.items() if n >= threshold}


def clean_page(text: str, noise: set[str]) -> str:
    """잡음 줄을 지우고, 문장 중간에서 끊긴 줄을 이어 붙인다."""
    lines = []
    for raw in text.translate(LIGATURES).splitlines():
        line = raw.strip()
        if not line or line in noise or NUMERIC_LINE.match(line):
            continue
        if lines and not BULLET_START.match(line) and not SENTENCE_END.search(lines[-1]):
            lines[-1] = f"{lines[-1]} {line}"   # 앞 줄이 문장 중간에서 끝났으면 이어 붙임
        else:
            lines.append(line)
    return "\n".join(lines)


def load_pdf(path: Path) -> list[Document]:
    if path.name not in DOCS:
        raise KeyError(f"{path.name}: rag/sources.py 에 먼저 등록하세요")
    info = doc_meta(path.name)

    import pymupdf   # 무거운 의존성은 쓸 때만
    with pymupdf.open(path) as pdf:
        pages = [page.get_text() for page in pdf]
    noise = repeated_lines(pages)

    docs = []
    for i, text in enumerate(pages):
        cleaned = clean_page(text, noise)
        if len(cleaned) < MIN_PAGE_CHARS:
            continue
        docs.append(Document(
            page_content=cleaned,
            metadata={**info, "source": path.name, "page": i + 1},   # page는 사람 기준 1부터
        ))
    return docs


def run(chunk_size: int = 1000) -> Path:
    pdfs = sorted(p for p in RAW_DIR.glob("*.pdf") if p.name in DOCS)
    missing = sorted(set(DOCS) - {p.name for p in pdfs})
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size, chunk_overlap=chunk_size // 10  # length_function=len → 문자 기준
    )

    all_chunks = []
    for path in pdfs:
        pages = load_pdf(path)
        chunks = splitter.split_documents(pages)
        all_chunks.extend(chunks)
        print(f"{path.name}: {len(pages)}쪽 → 청크 {len(chunks)}개")

    out_path = OUT_DIR / f"chunks_{chunk_size}.jsonl"
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        for i, c in enumerate(all_chunks):
            f.write(json.dumps({"id": i, "text": c.page_content, **c.metadata}, ensure_ascii=False) + "\n")

    print(f"\n총 청크 {len(all_chunks)}개 → {out_path.relative_to(ROOT)}")
    if missing:
        print("아직 없는 문서:", ", ".join(missing))
    return out_path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--chunk-size", type=int, default=1000, help="청크 크기(문자 수). 겹침은 10%")
    run(parser.parse_args().chunk_size)


if __name__ == "__main__":
    main()
