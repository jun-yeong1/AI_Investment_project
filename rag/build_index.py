"""청크를 임베딩해 FAISS 인덱스를 파일로 저장한다. 한 번 만들면 다시 임베딩하지 않는다.

실행: python -m rag.build_index --model bge-m3 --chunk-size 1000
결과: data/index/bge-m3_1000/ (index.faiss, index.pkl)
"""
import argparse
import time

from langchain_community.vectorstores import FAISS

from rag.retriever import INDEX_DIR, MODELS, STEmbeddings, load_chunks


def run(model: str = "bge-m3", chunk_size: int = 1000):
    out = INDEX_DIR / f"{model}_{chunk_size}"
    if out.exists():
        print(f"{out.name} 이미 있음 — 다시 만들려면 폴더를 지우고 실행")
        return out
    docs = load_chunks(chunk_size)
    print(f"청크 {len(docs)}개, 모델 {MODELS[model]['name']}")
    start = time.time()
    FAISS.from_documents(docs, STEmbeddings(model)).save_local(str(out))
    print(f"저장: data/index/{out.name}  ({time.time() - start:.0f}초)")
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="bge-m3", choices=list(MODELS))
    parser.add_argument("--chunk-size", type=int, default=1000)
    args = parser.parse_args()
    run(args.model, args.chunk_size)


if __name__ == "__main__":
    main()
