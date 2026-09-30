"""검색 성능 평가: Hit Rate@K, MRR

평가셋: data/eval/questions.jsonl — 한 줄에 질문 하나
  {"question": "...", "doc_type": "규제", "gold_source": "regulation_FDA_expedited_programs_2014.pdf", "gold_pages": [13, 14]}
정답은 청크 번호가 아니라 문서 · 쪽이다. 그래야 청크 크기를 바꿔도 같은 기준으로 비교할 수 있다.
검색된 청크의 (문서, 쪽)이 정답에 들어가면 적중으로 본다.

실행 예
  python -m rag.eval_retriever                  # 만들어 둔 인덱스 전부 비교
  python -m rag.eval_retriever --modes bm25     # 모델 없이 BM25만
"""
import argparse
import csv
import json
from pathlib import Path

from rag.retriever import INDEX_DIR, get_retriever

ROOT = Path(__file__).resolve().parents[1]
EVAL_PATH = ROOT / "data" / "eval" / "questions.jsonl"
K_VALUES = (1, 3, 5)


def evaluate(questions, mode, model, chunk_size):
    hits = {k: 0 for k in K_VALUES}
    rr_sum = 0.0
    for q in questions:
        retriever = get_retriever(q["doc_type"], k=max(K_VALUES), mode=mode, model=model, chunk_size=chunk_size)
        docs = retriever.invoke(q["question"])[: max(K_VALUES)]
        rank = next((i + 1 for i, d in enumerate(docs)
                     if d.metadata["source"] == q["gold_source"] and d.metadata["page"] in q["gold_pages"]), None)
        for k in K_VALUES:
            hits[k] += rank is not None and rank <= k
        rr_sum += 1 / rank if rank else 0
    n = len(questions)
    return {**{f"Hit@{k}": hits[k] / n for k in K_VALUES}, "MRR": rr_sum / n}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--modes", nargs="+", default=["bm25", "dense", "ensemble"])
    parser.add_argument("--chunk-sizes", nargs="+", type=int, default=[500, 1000, 1500])
    args = parser.parse_args()

    questions = [json.loads(line) for line in EVAL_PATH.open(encoding="utf-8")]
    models = sorted({p.name.rsplit("_", 1)[0] for p in INDEX_DIR.glob("*_*")}) or ["bge-m3"]

    rows = []
    for size in args.chunk_sizes:
        for mode in args.modes:
            for model in (models if mode != "bm25" else ["-"]):
                if mode != "bm25" and not (INDEX_DIR / f"{model}_{size}").exists():
                    continue
                result = evaluate(questions, mode, model if model != "-" else "bge-m3", size)
                rows.append({"chunk": size, "mode": mode, "model": model, **result})
                print(f"chunk {size:>4} | {mode:8} | {model:11} | "
                      + "  ".join(f"{k} {v:.3f}" for k, v in result.items()))

    out = ROOT / "data" / "eval" / "results.csv"
    with out.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    print(f"\n질문 {len(questions)}개, 결과 저장: {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
