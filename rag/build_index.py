"""청크를 임베딩해 FAISS 인덱스를 파일로 저장한다. 한 번 만들면 다시 임베딩하지 않는다.

실행: python -m rag.build_index --model bge-m3 --chunk r1000
결과: data/index/bge-m3_r1000/ (index.faiss, index.pkl) · 만든 시간은 data/index/build_times.json
"""
import argparse
import json
import time

from langchain_community.vectorstores import FAISS

from rag import settings
from rag.parse_pdfs import CHUNKINGS
from rag.retriever import INDEX_DIR, MODELS, STEmbeddings, load_chunks

TIMES = INDEX_DIR / "build_times.json"


def run(model: str = settings.MODEL, chunk: str = settings.CHUNK):
    out = INDEX_DIR / f"{model}_{chunk}"
    if out.exists():
        print(f"{out.name} 이미 있음 — 다시 만들려면 폴더를 지우고 실행")
        return out
    docs = load_chunks(chunk)
    print(f"[{model} · {chunk}] 청크 {len(docs)}개 임베딩 중 ({MODELS[model]['name']})")
    start = time.time()
    FAISS.from_documents(docs, STEmbeddings(model)).save_local(str(out))
    seconds = round(time.time() - start, 1)
    times = json.loads(TIMES.read_text()) if TIMES.exists() else {}
    times[out.name] = seconds
    TIMES.write_text(json.dumps(times, indent=2))
    print(f"저장: data/index/{out.name}  ({seconds:.0f}초)")
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=settings.MODEL, choices=list(MODELS))
    parser.add_argument("--chunk", default=settings.CHUNK, choices=list(CHUNKINGS))
    args = parser.parse_args()
    run(args.model, args.chunk)


if __name__ == "__main__":
    main()
