"""검색기 모듈: 에이전트는 get_retriever(doc_type)만 부르면 된다.

구성 (수업 14-Retriever와 같은 방식)
  - Dense : 오픈소스 임베딩(기본 bge-m3) + FAISS, doc_type 필터
  - Sparse: BM25 + Kiwi 형태소 분석 (doc_type별로 따로 만든다 — BM25Retriever에는 필터가 없음)
  - 합치기: EnsembleRetriever 0.5 / 0.5 (순위 기반 RRF)

사용 예 (저장소 루트에서)
  from rag.retriever import get_retriever
  docs = get_retriever("규제").invoke("희귀의약품 지정 요건")

에이전트는 보통 rag.rag_search.rag_search() 를 쓴다 (질문 재작성 · 관련성 채점 · 웹 보강 포함).
"""
import json
from functools import lru_cache
from pathlib import Path

from kiwipiepy import Kiwi
from langchain_classic.retrievers import EnsembleRetriever
from langchain_community.retrievers import BM25Retriever
from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings

from rag.sources import DOC_TYPES

ROOT = Path(__file__).resolve().parents[1]
CHUNK_DIR = ROOT / "data" / "processed"
INDEX_DIR = ROOT / "data" / "index"

# 임베딩 후보 — e5는 질문/문서 앞에 접두어를 붙여야 제 성능이 나온다
MODELS = {
    "bge-m3":      {"name": "BAAI/bge-m3", "query": "", "doc": ""},
    "e5-large":    {"name": "intfloat/multilingual-e5-large", "query": "query: ", "doc": "passage: "},
    "ko-sroberta": {"name": "jhgan/ko-sroberta-multitask", "query": "", "doc": ""},
}


class STEmbeddings(Embeddings):
    """sentence-transformers 모델을 LangChain 임베딩 인터페이스로 감싼다."""

    def __init__(self, key: str = "bge-m3"):
        from sentence_transformers import SentenceTransformer   # 무거워서 쓸 때만 불러온다
        cfg = MODELS[key]
        self.q_prefix, self.d_prefix = cfg["query"], cfg["doc"]
        self.model = SentenceTransformer(cfg["name"])

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        vecs = self.model.encode([self.d_prefix + t for t in texts], batch_size=16,
                                 normalize_embeddings=True, show_progress_bar=True)
        return vecs.tolist()

    def embed_query(self, text: str) -> list[float]:
        return self.model.encode(self.q_prefix + text, normalize_embeddings=True).tolist()


_kiwi = Kiwi()


def kiwi_tokenize(text: str) -> list[str]:
    """명사 · 동사 · 형용사 · 외국어(영문)만 남긴다. 영문은 소문자로 맞춘다."""
    return [t.form.lower() if t.tag == "SL" else t.form
            for t in _kiwi.tokenize(text)
            if t.tag in ("NNG", "NNP", "NNB", "VV", "VA", "SL", "SN")]


@lru_cache
def load_chunks(chunk_size: int = 1000) -> list[Document]:
    path = CHUNK_DIR / f"chunks_{chunk_size}.jsonl"
    docs = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            text = row.pop("text")
            docs.append(Document(page_content=text, metadata=row))
    return docs


@lru_cache
def load_embeddings(model: str = "bge-m3") -> STEmbeddings:
    return STEmbeddings(model)


@lru_cache
def load_faiss(model: str = "bge-m3", chunk_size: int = 1000) -> FAISS:
    path = INDEX_DIR / f"{model}_{chunk_size}"
    if not path.exists():
        raise FileNotFoundError(f"{path} 없음 — 먼저 python -m rag.build_index --model {model} --chunk-size {chunk_size}")
    return FAISS.load_local(str(path), load_embeddings(model), allow_dangerous_deserialization=True)


def get_retriever(doc_type: str, k: int = 3, mode: str = "ensemble",
                  model: str = "bge-m3", chunk_size: int = 1000):
    """doc_type: "규제" | "기술" | "시장·사업성",  mode: "ensemble" | "bm25" | "dense" """
    if doc_type not in DOC_TYPES:
        raise ValueError(f"doc_type은 {DOC_TYPES} 중 하나")

    docs = [d for d in load_chunks(chunk_size) if d.metadata["doc_type"] == doc_type]
    bm25 = BM25Retriever.from_documents(docs, preprocess_func=kiwi_tokenize, k=k)
    if mode == "bm25":
        return bm25

    # FAISS 필터는 상위 fetch_k개를 뽑은 뒤 거른다 → 전체 청크 수로 두어 청크가 적은 doc_type도 빠지지 않게
    dense = load_faiss(model, chunk_size).as_retriever(
        search_kwargs={"k": k, "fetch_k": len(load_chunks(chunk_size)), "filter": {"doc_type": doc_type}})
    if mode == "dense":
        return dense

    return EnsembleRetriever(retrievers=[bm25, dense], weights=[0.5, 0.5])
