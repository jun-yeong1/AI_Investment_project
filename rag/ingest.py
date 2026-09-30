"""RAG 색인 생성: data/raw PDF → 쪽 추출(+OCR) → 정제 → 청킹 → 임베딩 → FAISS.

    uv run python -m rag.ingest [--force] [--chunk-size N] [--index-dir DIR]

결과(index-dir, 기본 data/index): index.faiss · index.pkl · chunks.jsonl · meta.json
쪽 단위 추출 결과는 data/processed/{doc_id}.pages.json 에 캐시한다(OCR 재실행 방지).
"""
import argparse
import hashlib
import json
import os
import re
import shutil
from pathlib import Path

import fitz  # PyMuPDF
from langchain_community.vectorstores import FAISS
from langchain_community.vectorstores.utils import DistanceStrategy
from langchain_core.documents import Document
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

import config
from rag.clean import clean_pages

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"
PROCESSED_DIR = ROOT / "data" / "processed"
INDEX_DIR = ROOT / "data" / "index"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def get_embeddings() -> HuggingFaceEmbeddings:
    # 정규화하면 내적 = 코사인 유사도
    return HuggingFaceEmbeddings(
        model_name=config.RAG_EMBEDDING_MODEL,
        encode_kwargs={"normalize_embeddings": True, "batch_size": 16},
    )


def _tessdata_dir() -> str:
    candidates = [
        os.environ.get("TESSDATA_PREFIX"),
        "/opt/homebrew/share/tessdata",
        "/usr/local/share/tessdata",
        "/usr/share/tesseract-ocr/5/tessdata",
        "/usr/share/tesseract-ocr/4.00/tessdata",
    ]
    for c in candidates:
        if c and (Path(c) / "kor.traineddata").exists():
            return c
    raise RuntimeError(
        "OCR용 tesseract 한국어 데이터(kor.traineddata)를 찾지 못했다. "
        "brew install tesseract tesseract-lang 후 TESSDATA_PREFIX를 지정한다."
    )


def _drop_ocr_noise(text: str) -> str:
    """차트 축·기호가 잘못 읽힌 짧은 줄(글자·숫자 3자 미만)을 버린다."""
    keep = [ln for ln in text.split("\n") if len(re.findall(r"[0-9A-Za-z가-힣]", ln)) >= 3]
    return "\n".join(keep)


def extract_pages(path: Path) -> list[dict]:
    """쪽 단위 원문 추출. 텍스트 층이 없는 쪽(스캔본)만 OCR로 대체한다."""
    pages = []
    with fitz.open(path) as doc:
        for i, page in enumerate(doc, start=1):
            text = page.get_text()
            ocr = False
            if len(text.strip()) < config.RAG_OCR_MIN_CHARS and page.get_images():
                if not shutil.which("tesseract"):
                    raise RuntimeError(f"{path.name} p{i}: OCR이 필요하지만 tesseract가 없다")
                os.environ["TESSDATA_PREFIX"] = _tessdata_dir()
                tp = page.get_textpage_ocr(language=config.RAG_OCR_LANG, dpi=config.RAG_OCR_DPI, full=True)
                text = _drop_ocr_noise(page.get_text(textpage=tp))
                ocr = True
            pages.append({"page": i, "text": text, "ocr": ocr})
    return pages


def load_source(src: dict) -> list[dict]:
    """정제까지 끝난 쪽 목록 [{"page", "text", "ocr"}]. 원본이 같으면 캐시를 쓴다."""
    path = RAW_DIR / src["file"]
    if not path.exists():
        raise FileNotFoundError(f"원본 PDF가 없다: {path}")
    digest = sha256(path)
    cache = PROCESSED_DIR / f"{src['doc_id']}.pages.json"
    if cache.exists():
        cached = json.loads(cache.read_text(encoding="utf-8"))
        if cached.get("sha256") == digest and cached.get("line_numbers") == bool(src.get("line_numbers")):
            return cached["pages"]

    raw = extract_pages(path)
    cleaned = clean_pages([p["text"] for p in raw], line_numbers=bool(src.get("line_numbers")))
    pages = [{"page": p["page"], "text": t, "ocr": p["ocr"]} for p, t in zip(raw, cleaned)]
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    cache.write_text(
        json.dumps(
            {"sha256": digest, "line_numbers": bool(src.get("line_numbers")), "pages": pages},
            ensure_ascii=False, indent=1,
        ),
        encoding="utf-8",
    )
    return pages


def chunk_pages(src: dict, pages: list[dict], chunk_size: int, chunk_overlap: int) -> list[Document]:
    """쪽 단위로 자른다(청크가 쪽 경계를 넘지 않아 doc·page가 정확하다)."""
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size, chunk_overlap=chunk_overlap,
        separators=["\n\n", "\n", ". ", " ", ""],
    )
    docs = []
    for p in pages:
        for seq, text in enumerate(splitter.split_text(p["text"])):
            if len(text.strip()) < config.RAG_MIN_CHUNK_CHARS:
                continue
            docs.append(Document(
                page_content=text,
                metadata={
                    "chunk_id": f"{src['doc_id']}-p{p['page']:03d}-{seq:02d}",
                    "doc_id": src["doc_id"],
                    "doc": src["doc"],
                    "doc_type": src["doc_type"],
                    "lang": src["lang"],
                    "page": p["page"],
                    "ocr": p["ocr"],
                },
            ))
    return docs


def build_index(
    chunk_size: int = config.RAG_CHUNK_SIZE,
    index_dir: Path = INDEX_DIR,
    force: bool = False,
) -> dict:
    index_dir = Path(index_dir)
    chunk_overlap = min(config.RAG_CHUNK_OVERLAP, chunk_size // 4)
    sources = {s["doc_id"]: sha256(RAW_DIR / s["file"]) for s in config.RAG_SOURCES if (RAW_DIR / s["file"]).exists()}
    signature = {
        "model": config.RAG_EMBEDDING_MODEL, "chunk_size": chunk_size,
        "chunk_overlap": chunk_overlap, "sources": sources,
    }
    meta_path = index_dir / "meta.json"
    if not force and meta_path.exists() and (index_dir / "index.faiss").exists():
        old = json.loads(meta_path.read_text(encoding="utf-8"))
        if all(old.get(k) == v for k, v in signature.items()):
            print(f"색인이 최신이다 ({old['n_chunks']}청크). 다시 만들려면 --force")
            return old

    docs: list[Document] = []
    for src in config.RAG_SOURCES:
        pages = load_source(src)
        chunks = chunk_pages(src, pages, chunk_size, chunk_overlap)
        n_ocr = sum(p["ocr"] for p in pages)
        print(f"[{src['doc_type']:10}] {src['doc_id']:15} {len(pages):3}쪽 → {len(chunks):4}청크"
              + (f" (OCR {n_ocr}쪽)" if n_ocr else ""))
        docs.extend(chunks)

    print(f"임베딩: {config.RAG_EMBEDDING_MODEL} · 총 {len(docs)}청크")
    store = FAISS.from_documents(
        docs, get_embeddings(), distance_strategy=DistanceStrategy.MAX_INNER_PRODUCT
    )
    index_dir.mkdir(parents=True, exist_ok=True)
    store.save_local(str(index_dir))
    with (index_dir / "chunks.jsonl").open("w", encoding="utf-8") as f:
        for d in docs:
            f.write(json.dumps({**d.metadata, "text": d.page_content}, ensure_ascii=False) + "\n")
    meta = {**signature, "n_chunks": len(docs)}
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"저장: {index_dir}")
    return meta


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--force", action="store_true", help="색인이 최신이어도 다시 만든다")
    ap.add_argument("--chunk-size", type=int, default=config.RAG_CHUNK_SIZE)
    ap.add_argument("--index-dir", type=Path, default=INDEX_DIR)
    args = ap.parse_args()
    build_index(chunk_size=args.chunk_size, index_dir=args.index_dir, force=args.force)
