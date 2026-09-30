"""검색 성능 평가: Hit Rate@K, MRR

평가셋: data/eval/questions.jsonl — 한 줄에 질문 하나
  {"question": "한국어 질문", "question_en": "English query", "doc_type": "regulation",
   "gold_source": "regulation_FDA_expedited_programs_2014.pdf", "gold_pages": [13]}

- 정답은 청크 번호가 아니라 문서 · 쪽이다. 청킹 방식이 달라도 같은 기준으로 비교할 수 있다.
- 검색된 청크의 (문서, 쪽)이 정답에 들어가면 적중이다.
- rag_search와 똑같이 한국어 · 영어 질문을 함께 보내 결과를 합친다 (langs로 한국어만도 가능).
"""
import json
import time
from pathlib import Path

from rag.retriever import search

ROOT = Path(__file__).resolve().parents[1]
EVAL_PATH = ROOT / "data" / "eval" / "questions.jsonl"
K_VALUES = (1, 3, 5)


def load_questions(path: Path = EVAL_PATH) -> list[dict]:
    return [json.loads(line) for line in path.open(encoding="utf-8") if line.strip()]


def first_hit_rank(docs, q) -> int | None:
    return next((i + 1 for i, d in enumerate(docs)
                 if d.metadata["source"] == q["gold_source"] and d.metadata["page"] in q["gold_pages"]), None)


def evaluate(questions: list[dict], mode: str, model: str, chunk: str,
             langs: tuple[str, ...] = ("ko", "en")) -> dict:
    k = max(K_VALUES)
    hits = {kv: 0 for kv in K_VALUES}
    rr_sum, seconds = 0.0, 0.0
    # 워밍업: 모델 · 인덱스를 불러오는 시간이 첫 질문의 검색 시간에 섞이지 않게 한 번 미리 검색
    search(questions[0]["doc_type"], [questions[0]["question"]], k=k, mode=mode, model=model, chunk=chunk)
    for q in questions:
        queries = [q["question"] if "ko" in langs else None, q.get("question_en") if "en" in langs else None]
        start = time.time()
        docs = search(q["doc_type"], [x for x in queries if x], k=k, mode=mode, model=model, chunk=chunk)[:k]
        seconds += time.time() - start
        rank = first_hit_rank(docs, q)
        for kv in K_VALUES:
            hits[kv] += rank is not None and rank <= kv
        rr_sum += 1 / rank if rank else 0
    n = len(questions)
    return {**{f"Hit@{kv}": round(hits[kv] / n, 3) for kv in K_VALUES},
            "MRR": round(rr_sum / n, 3), "sec/질문": round(seconds / n, 3)}
