"""RAG 문서 파싱: PDF → 텍스트(표 · 그림 포함) → 청크 → data/processed/chunks_{방식}.jsonl

실행: python -m rag.parse_pdfs [--chunk r1000] [--no-vision]   (저장소 루트에서)

원칙: 정보는 버리지 않는다. 지우는 것은 편집 흔적(줄번호 · 쪽번호)과 반복 머리말의 중복뿐이다.

흐름
  1. 쪽 단위 글자 추출 (PyMuPDF) — 쪽 번호를 메타데이터로 남겨 인용에 쓴다
  2. 정제
     - 지움: 줄번호(FDA처럼 줄마다 번호가 붙은 문서만), 쪽번호("- 7 -", "18/ February 2021")
     - 한 번만 남김: 매 쪽 위 · 아래에 반복되는 머리말 · 꼬리말 (첫 쪽에만 남긴다)
     - 그대로 둠: 표 · 그래프에서 나온 숫자, 목차, 참고문헌
     - 문장 중간에서 끊긴 줄은 이어 붙이고, 글머리(□ ❍ ㅇ * -)는 새 줄로 유지, 합자(ﬁ → fi) 풀기
  3. 표 · 그래프 · 그림 전사 (rag/vision.py) — 쪽을 이미지로 바꿔 비전 LLM이 표는 마크다운 표로,
     그래프는 "라벨: 값"으로 옮긴다. 글자가 이미지로만 된 쪽(표지 등)은 쪽 전체를 옮긴다. 결과는 캐시
  4. 청크 분할 — CHUNKINGS 중 하나
       r500 / r1000 / r1500 : 문자 기준 재귀 분할(겹침 10%)
       page                 : 한 쪽 = 한 청크 (문단 · 표가 쪽 안에서 끊기지 않음)
  5. data/processed/chunks_{방식}.jsonl 저장 — 사람이 열어 보고 청크 품질을 확인할 수 있게
"""
import argparse
import json
import re
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from rag.sources import DOCS, doc_meta

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw"
OUT_DIR = ROOT / "data" / "processed"

MIN_PAGE_CHARS = 50                          # 글자 추출이 이보다 적으면 이미지로 된 쪽 → 쪽 전체를 비전으로 전사
EDGE_LINES = 3                               # 쪽 위 · 아래 몇 줄을 머리말 · 꼬리말 후보로 볼지
REPEAT_RATIO = 0.3                           # 전체 쪽의 30% 이상에서 위 · 아래에 반복되면 머리말 · 꼬리말
PAGE_MARK = re.compile(r"^- ?\d+ ?-$|^\d+ ?/ ?[A-Z][a-z]+ \d{4}$")   # 쪽번호 "- 7 -", "18/ February 2021"
INT_LINE = re.compile(r"^\d{1,4}$")
BULLET_START = re.compile(r"^(□|❍|○|ㅇ|◦|•|·|\*|-|–|➡|√|※|\d+\.|[가-하]\.|[IVX]+\.|[A-Z]\.)\s?")
SENTENCE_END = re.compile(r"[.!?。:;)]$|다\.?$|음\.?$|함\.?$")
# 영문 PDF의 합자(ﬁ ﬂ 등)를 풀어야 "first" 같은 검색어가 BM25에서 맞는다
LIGATURES = str.maketrans({"ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi", "ﬄ": "ffl", "ﬅ": "st", "ﬆ": "st"})


def _lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def repeated_lines(pages: list[str]) -> set[str]:
    """여러 쪽의 위 · 아래 가장자리에 똑같이 나오는 줄(머리말 · 꼬리말)을 찾는다.
    쪽 가운데의 표 머리글(예: NDA/BLA)은 반복돼도 내용이므로 대상에서 뺀다."""
    counter = Counter()
    for text in pages:
        lines = _lines(text)
        counter.update(set(lines[:EDGE_LINES] + lines[-EDGE_LINES:]))
    threshold = max(3, int(len(pages) * REPEAT_RATIO))
    return {line for line, n in counter.items() if n >= threshold}


def is_line_numbered(pages: list[str]) -> bool:
    """줄마다 번호가 붙은 문서인지 — 숫자만 있는 줄이 많고 대부분 1씩 늘어나면 줄번호다."""
    ints = [int(line) for text in pages for line in _lines(text) if INT_LINE.match(line)]
    if len(ints) < 50:
        return False
    consecutive = sum(1 for a, b in zip(ints, ints[1:]) if b == a + 1)
    return consecutive / len(ints) > 0.6


def clean_page(text: str, drop: set[str], line_numbered: bool = False) -> str:
    """편집 흔적만 지우고, 문장 중간에서 끊긴 줄을 이어 붙인다."""
    raw_lines = _lines(text.translate(LIGATURES))
    edge = set(raw_lines[:2] + raw_lines[-2:])          # 쪽 맨 위 · 아래에 혼자 있는 숫자 = 쪽번호
    lines = []
    for line in raw_lines:
        if (line in drop or PAGE_MARK.match(line)
                or (INT_LINE.match(line) and (line_numbered or line in edge))):
            continue
        if lines and not BULLET_START.match(line) and not SENTENCE_END.search(lines[-1]):
            lines[-1] = f"{lines[-1]} {line}"   # 앞 줄이 문장 중간에서 끝났으면 이어 붙임
        else:
            lines.append(line)
    return "\n".join(lines)


def load_pdf(path: Path, vision: bool = True) -> list[Document]:
    if path.name not in DOCS:
        raise KeyError(f"{path.name}: rag/sources.py 에 먼저 등록하세요")
    info = doc_meta(path.name)

    import pymupdf   # 무거운 의존성은 쓸 때만
    with pymupdf.open(path) as pdf:
        pages = [page.get_text() for page in pdf]
    headers = repeated_lines(pages)
    line_numbered = is_line_numbered(pages)

    texts, seen = [], set()
    for text in pages:
        texts.append(clean_page(text, drop=headers & seen, line_numbered=line_numbered))  # 머리말은 처음 한 번만
        seen |= headers & set(_lines(text))

    image_only = [len(t) < MIN_PAGE_CHARS for t in texts]
    if vision:
        from rag.vision import describe_page
        with ThreadPoolExecutor(max_workers=6) as pool:
            extras = list(pool.map(lambda i: describe_page(path, i + 1, full=image_only[i]), range(len(pages))))
    else:
        extras = [""] * len(pages)

    docs = []
    for i, (text, extra) in enumerate(zip(texts, extras)):
        if image_only[i]:
            content = extra                              # 이미지로 된 쪽: 비전 전사가 곧 본문
        else:
            content = text + (f"\n\n[표·그림]\n{extra}" if extra else "")
        if not content.strip():
            continue
        docs.append(Document(
            page_content=content,
            metadata={**info, "source": path.name, "page": i + 1,   # page는 사람 기준 1부터
                      "has_figure": bool(extra), "image_only": image_only[i]},
        ))
    return docs


# 청킹 방식 이름 → (방법, 크기). 실험에서 이 이름으로 비교한다
CHUNKINGS = {"r500": ("recursive", 500), "r1000": ("recursive", 1000),
             "r1500": ("recursive", 1500), "page": ("page", None)}


def run(chunk: str = "r1000", vision: bool = True) -> Path:
    method, size = CHUNKINGS[chunk]
    pdfs = sorted(p for p in RAW_DIR.glob("*.pdf") if p.name in DOCS)
    missing = sorted(set(DOCS) - {p.name for p in pdfs})

    all_chunks = []
    for path in pdfs:
        pages = load_pdf(path, vision=vision)
        if method == "page":
            chunks = pages
        else:
            splitter = RecursiveCharacterTextSplitter(chunk_size=size, chunk_overlap=size // 10)  # 문자 기준
            chunks = splitter.split_documents(pages)
        all_chunks.extend(chunks)
        print(f"{path.name}: {len(pages)}쪽 → 청크 {len(chunks)}개")

    out_path = OUT_DIR / f"chunks_{chunk}.jsonl"
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        for i, c in enumerate(all_chunks):
            f.write(json.dumps({"id": i, "text": c.page_content, **c.metadata}, ensure_ascii=False) + "\n")

    print(f"\n[{chunk}] 총 청크 {len(all_chunks)}개 → {out_path.relative_to(ROOT)}")
    if missing:
        print("아직 없는 문서:", ", ".join(missing))
    return out_path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--chunk", default="r1000", choices=list(CHUNKINGS))
    parser.add_argument("--no-vision", action="store_true", help="표 · 그림 전사 없이 글자만 (API 키 없을 때)")
    args = parser.parse_args()
    run(args.chunk, vision=not args.no_vision)


if __name__ == "__main__":
    main()
