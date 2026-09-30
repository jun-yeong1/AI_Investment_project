"""rag_search(query, doc_type) -> list[RagHit]: BM25(Kiwi) + FAISS 하이브리드 검색.

    uv run python -m rag.search "임상 1상 성공률" --type market [-k 5]

- doc_type 메타데이터로 에이전트별 문서만 검색한다.
- 두 검색의 순위를 RRF로 합치고, dense 코사인 유사도가 하한 미만이면 관련 없음으로 본다.
- 검색 실패·관련 없음은 예외 대신 []를 반환한다(웹 보강 여부는 호출한 Agent가 판단).
- 질문 다시 쓰기·한/영 질문 생성은 Agent 몫이다. 여기서는 질문 한 개를 받는다.
"""
import argparse
import json
import logging
import re
from pathlib import Path

from langchain_community.vectorstores import FAISS
from langchain_community.vectorstores.utils import DistanceStrategy
from rank_bm25 import BM25Okapi

import config
from rag.ingest import INDEX_DIR, get_embeddings
from rag.types import DocType, RagHit

log = logging.getLogger(__name__)

_RRF_K = 60          # RRF 상수(관례값)
_CANDIDATES = 20     # 검색 방식마다 순위에 올리는 후보 수
_KEEP_TAGS = ("N", "XR", "SL", "SN")   # Kiwi 품사: 명사류 · 어근 · 외국어 · 숫자

_kiwi = None
_indexes: dict[str, "_Index"] = {}


def tokenize(text: str) -> list[str]:
    """BM25용 토큰. 한국어는 Kiwi 형태소, 영문은 소문자 낱말로 나뉜다."""
    global _kiwi
    if _kiwi is None:
        from kiwipiepy import Kiwi
        _kiwi = Kiwi()
    toks = []
    for t in _kiwi.tokenize(text):
        if t.tag.startswith(_KEEP_TAGS) or (t.tag.startswith("V") and len(t.form) > 1):
            toks.append(t.form.lower())
    return toks


class _Index:
    def __init__(self, index_dir: Path):
        self.store = FAISS.load_local(
            str(index_dir), get_embeddings(),
            allow_dangerous_deserialization=True,   # 우리가 만든 파일만 읽는다
            distance_strategy=DistanceStrategy.MAX_INNER_PRODUCT,
        )
        chunks = [json.loads(ln) for ln in (index_dir / "chunks.jsonl").read_text(encoding="utf-8").splitlines()]
        self.by_id = {c["chunk_id"]: c for c in chunks}
        # doc_type별 BM25: 해당 문서들만으로 IDF를 계산한다
        self.bm25: dict[str, tuple[list[dict], BM25Okapi]] = {}
        for dt in {c["doc_type"] for c in chunks}:
            sub = [c for c in chunks if c["doc_type"] == dt]
            self.bm25[dt] = (sub, BM25Okapi([tokenize(c["text"]) for c in sub]))


def _get_index(index_dir: Path) -> _Index:
    key = str(index_dir)
    if key not in _indexes:
        _indexes[key] = _Index(index_dir)
    return _indexes[key]


def rag_search(
    query: str,
    doc_type: DocType,
    k: int = config.RAG_TOP_K,
    index_dir: Path | str = INDEX_DIR,
) -> list[RagHit]:
    try:
        if doc_type not in config.DOC_TYPES:
            raise ValueError(f"알 수 없는 doc_type: {doc_type!r}")
        if not query.strip():
            return []
        idx = _get_index(Path(index_dir))
        subset, bm25 = idx.bm25[doc_type]

        # dense: 해당 doc_type 전체의 코사인 유사도(문서 수가 적어 전수 계산)
        dense = idx.store.similarity_search_with_score(
            query, k=len(subset), fetch_k=idx.store.index.ntotal, filter={"doc_type": doc_type}
        )
        sim = {d.metadata["chunk_id"]: float(s) for d, s in dense}   # 이미 유사도 내림차순

        # sparse: 점수 0(겹치는 단어 없음)은 순위에서 뺀다
        scores = bm25.get_scores(tokenize(query))
        sparse = [subset[i]["chunk_id"] for i in sorted(range(len(subset)), key=lambda i: -scores[i]) if scores[i] > 0]

        fused: dict[str, float] = {}
        rankings = (list(sim)[:_CANDIDATES], sparse[:_CANDIDATES])
        for weight, ranking in zip(config.RAG_FUSION_WEIGHTS, rankings):
            for rank, cid in enumerate(ranking, start=1):
                fused[cid] = fused.get(cid, 0.0) + weight / (_RRF_K + rank)

        hits: list[RagHit] = []
        for cid in sorted(fused, key=fused.get, reverse=True):
            if sim.get(cid, 0.0) < config.RAG_MIN_SIMILARITY:
                continue
            c = idx.by_id[cid]
            hits.append({
                "chunk_id": cid, "doc": c["doc"], "page": c["page"],
                "text": c["text"], "score": round(sim[cid], 4),
            })
            if len(hits) == k:
                break
        return hits
    except Exception:
        log.exception("rag_search 실패 (query=%r, doc_type=%r)", query, doc_type)
        return []


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("query")
    ap.add_argument("--type", dest="doc_type", required=True, choices=config.DOC_TYPES)
    ap.add_argument("-k", type=int, default=config.RAG_TOP_K)
    ap.add_argument("--index-dir", type=Path, default=INDEX_DIR)
    args = ap.parse_args()
    results = rag_search(args.query, args.doc_type, k=args.k, index_dir=args.index_dir)
    if not results:
        print("[] (검색 실패 또는 관련 없음)")
    for i, h in enumerate(results, 1):
        body = re.sub(r"\s+", " ", h["text"])[:200]
        print(f"{i}. [{h['score']:.3f}] {h['chunk_id']} · {h['doc']} p.{h['page']}\n   {body}")
