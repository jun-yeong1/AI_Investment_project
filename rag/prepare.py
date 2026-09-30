"""RAG 준비를 한 번에: 문서 받기 → 파싱 → 임베딩 인덱스.

실행: python -m rag.prepare                (기본: 청크 1000자, bge-m3)
      python -m rag.prepare --chunk-size 500 --model e5-large
처음 실행하면 임베딩 모델을 내려받는다 (bge-m3 약 2.3GB).
"""
import argparse

from rag import build_index, download_docs, parse_pdfs
from rag.retriever import MODELS


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--chunk-size", type=int, default=1000)
    parser.add_argument("--model", default="bge-m3", choices=list(MODELS))
    args = parser.parse_args()

    print("== 1/3 문서 받기");  download_docs.main()
    print("\n== 2/3 파싱");     parse_pdfs.run(args.chunk_size)
    print("\n== 3/3 인덱스");   build_index.run(args.model, args.chunk_size)
    print("\n준비 완료 — from rag.rag_search import rag_search")


if __name__ == "__main__":
    main()
