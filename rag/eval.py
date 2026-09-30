"""검색 평가: Hit@3 · MRR. 정답은 청크 번호가 아니라 문서·쪽으로 정한다(청크 크기를 바꿔도 비교 가능).

    uv run python -m rag.eval [--index-dir DIR] [--questions FILE] [-k 10]

questions.jsonl 한 줄: {"id", "doc_type", "query", "doc_id", "pages": [정답 쪽, ...]}
- Hit@3: 상위 3개 청크 중 정답 문서·쪽의 청크가 있는 질문의 비율
- MRR: 정답 청크가 처음 나온 순위의 역수 평균(top-k 안에 없으면 0)
※ 유사도 하한(RAG_MIN_SIMILARITY)이 적용된 실제 rag_search 결과로 잰다.
"""
import argparse
import json
from collections import defaultdict
from pathlib import Path

from rag.ingest import INDEX_DIR, ROOT
from rag.search import rag_search

QUESTIONS = ROOT / "data" / "eval" / "questions.jsonl"


def load_questions(path: Path = QUESTIONS) -> list[dict]:
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def first_correct_rank(hits: list[dict], doc_id: str, pages: list[int]) -> int | None:
    for rank, h in enumerate(hits, start=1):
        if h["chunk_id"].rsplit("-p", 1)[0] == doc_id and h["page"] in pages:
            return rank
    return None


def evaluate(questions: list[dict], index_dir: Path = INDEX_DIR, k: int = 10) -> dict:
    rows = []
    for q in questions:
        hits = rag_search(q["query"], q["doc_type"], k=k, index_dir=index_dir)
        rows.append({**q, "rank": first_correct_rank(hits, q["doc_id"], q["pages"])})

    def summarize(rs: list[dict]) -> dict:
        n = len(rs)
        return {
            "n": n,
            "hit@3": sum(1 for r in rs if r["rank"] and r["rank"] <= 3) / n,
            "mrr": sum(1 / r["rank"] for r in rs if r["rank"]) / n,
        }

    by_type = defaultdict(list)
    for r in rows:
        by_type[r["doc_type"]].append(r)
    return {
        "rows": rows,
        "overall": summarize(rows),
        "by_type": {t: summarize(rs) for t, rs in by_type.items()},
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--index-dir", type=Path, default=INDEX_DIR)
    ap.add_argument("--questions", type=Path, default=QUESTIONS)
    ap.add_argument("-k", type=int, default=10)
    args = ap.parse_args()
    res = evaluate(load_questions(args.questions), args.index_dir, args.k)
    for r in res["rows"]:
        print(f"{r['id']} [{r['doc_type']:10}] 정답순위={r['rank'] or '-':>2}  {r['query']}")
    print()
    for name, s in [*res["by_type"].items(), ("전체", res["overall"])]:
        print(f"{name:10} n={s['n']:2}  Hit@3={s['hit@3']:.3f}  MRR={s['mrr']:.3f}")
