"""청킹 방식 × 임베딩 모델 × 검색 방식을 비교해 가장 좋은 조합을 고른다.

실행 (저장소 루트에서)
  python -m rag.experiment                                   # 전부: 청킹 4 × 모델 3 × 검색 3
  python -m rag.experiment --models bge-m3                   # 받아 둔 모델만
  python -m rag.experiment --chunks r1000 page --langs ko    # 일부만, 한국어 질문만

하는 일
  1. 청크 파일이 없으면 만든다 (parse_pdfs)
  2. 인덱스가 없으면 만든다 (build_index — 모델을 처음 쓰면 내려받는다)
  3. data/eval/questions.jsonl 로 Hit@1·3·5, MRR, 질문당 검색 시간을 잰다
  4. 결과를 data/eval/results.csv · results.md 에 저장하고,
     가장 좋은 조합을 data/eval/best_config.json 에 저장한다 → rag_search가 이 설정을 쓴다

선택 규칙 (설계서 B-2)
  MRR이 가장 높은 조합을 고른다. 질문 30개에서 1~2개 차이(MRR 2/질문수)는 오차로 보고,
  그 범위 안에 검색이 20% 이상 빠른 조합이 있으면 그것을 고른다.
"""
import argparse
import csv
import gc
import json
import os

# 실험은 검색을 수천 번 부른다 — LangSmith 추적을 끄지 않으면 호출마다 기록을 보내 느려지고 한도를 넘는다
os.environ["LANGSMITH_TRACING"] = os.environ["LANGCHAIN_TRACING_V2"] = "false"

from rag import build_index, parse_pdfs
from rag.eval_retriever import EVAL_PATH, evaluate, load_questions
from rag.retriever import CHUNK_DIR, INDEX_DIR, MODELS, clear_caches
from rag.settings import BEST_CONFIG

OUT_DIR = EVAL_PATH.parent


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--chunks", nargs="+", default=list(parse_pdfs.CHUNKINGS), choices=list(parse_pdfs.CHUNKINGS))
    parser.add_argument("--models", nargs="+", default=list(MODELS), choices=list(MODELS))
    parser.add_argument("--modes", nargs="+", default=["bm25", "faiss", "ensemble"],
                        choices=["bm25", "faiss", "ensemble"])
    parser.add_argument("--langs", nargs="+", default=["ko", "en"], choices=["ko", "en"])
    args = parser.parse_args()

    questions = load_questions()
    n = len(questions)
    print(f"평가셋 {n}문항 · 청킹 {args.chunks} · 모델 {args.models} · 검색 {args.modes} · 질문 언어 {args.langs}\n")

    # 1. 청크
    for chunk in args.chunks:
        if not (CHUNK_DIR / f"chunks_{chunk}.jsonl").exists():
            parse_pdfs.run(chunk)

    rows = []

    def record(chunk, model, mode):
        result = evaluate(questions, mode, model, chunk, tuple(args.langs))
        row = {"chunk": chunk, "model": model if mode != "bm25" else "-", "mode": mode, **result}
        rows.append(row)
        print(f"{chunk:>5} | {row['model']:11} | {mode:8} | "
              + "  ".join(f"{key} {val}" for key, val in result.items()))

    # 2~3. BM25는 임베딩과 무관 → 청킹마다 한 번
    if "bm25" in args.modes:
        for chunk in args.chunks:
            record(chunk, "bge-m3", "bm25")

    for model in args.models:                      # 모델 하나씩 올렸다 내려서 메모리를 아낀다
        for chunk in args.chunks:
            if not (INDEX_DIR / f"{model}_{chunk}").exists():
                build_index.run(model, chunk)
            for mode in [m for m in args.modes if m != "bm25"]:
                record(chunk, model, mode)
        clear_caches()
        gc.collect()

    # 4. 저장
    rows.sort(key=lambda r: r["MRR"], reverse=True)
    with (OUT_DIR / "results.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

    top = rows[0]
    near = [r for r in rows if top["MRR"] - r["MRR"] <= 2 / n]           # 질문 1~2개 차이는 오차
    faster = [r for r in near if r["sec/질문"] <= 0.8 * top["sec/질문"]]    # 20% 이상 빠를 때만 바꾼다
    best = min(faster, key=lambda r: r["sec/질문"]) if faster else top
    best_mrr = top["MRR"]
    chosen = {"chunk": best["chunk"], "model": best["model"] if best["model"] != "-" else "bge-m3",
              "mode": best["mode"], "MRR": best["MRR"], "Hit@3": best["Hit@3"], "questions": n,
              "langs": args.langs, "rule": f"MRR 최고 조합. 단 MRR 차이 2/{n} 이내이면서 20% 이상 빠른 조합이 있으면 그것 (최고 MRR {best_mrr})"}
    BEST_CONFIG.write_text(json.dumps(chosen, ensure_ascii=False, indent=2), encoding="utf-8")

    header = "| 청킹 | 임베딩 | 검색 | Hit@1 | Hit@3 | Hit@5 | MRR | 질문당 초 |\n|---|---|---|---|---|---|---|---|\n"
    lines = "".join(f"| {r['chunk']} | {r['model']} | {r['mode']} | {r['Hit@1']} | {r['Hit@3']} | {r['Hit@5']} "
                    f"| {r['MRR']} | {r['sec/질문']} |\n" for r in rows)
    (OUT_DIR / "results.md").write_text(
        f"# RAG 검색 실험 결과\n\n평가셋 {n}문항, 질문 언어 {'+'.join(args.langs)}, MRR 순\n\n{header}{lines}\n"
        f"**선택**: 청킹 `{chosen['chunk']}` · 임베딩 `{chosen['model']}` · 검색 `{chosen['mode']}` — {chosen['rule']}\n",
        encoding="utf-8")

    print(f"\n선택: 청킹 {chosen['chunk']} · 임베딩 {chosen['model']} · 검색 {chosen['mode']} "
          f"(MRR {chosen['MRR']}, Hit@3 {chosen['Hit@3']})")
    print(f"저장: {BEST_CONFIG.relative_to(OUT_DIR.parent.parent)}, data/eval/results.md, results.csv")


if __name__ == "__main__":
    main()
