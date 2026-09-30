# RAG 모듈 — 에이전트 팀 사용법

## 1. 준비 (처음 한 번)

```bash
pip install -r requirements.txt
python -m rag.prepare          # 문서 받기 → 파싱 → bge-m3 인덱스 (첫 실행 때 모델 약 2.3GB 다운로드)
```

`.env`에 `OPENAI_API_KEY`가 필요하다. `TAVILY_API_KEY`가 있으면 문서에 답이 없을 때 웹 검색으로 보강한다.

## 2. 에이전트에서 쓰기 (계약: `rag/types.py`)

```python
from rag.rag_search import rag_search

hits = rag_search("희귀의약품 지정이 신약 개발 위험에서 어떤 의미인가", "regulation")
# 선택: pipeline=state["pipeline"] 을 주면 검색 질문을 물질 · 적응증 단위로 만든다
```

| 에이전트 | doc_type | 들어 있는 문서 |
|---|---|---|
| 규제 | `"regulation"` | FDA Expedited Programs (신속심사 지정 요건) |
| 기술·파이프라인 | `"tech"` | KISTEP AI 신약 브리프, Jayatunga(2024) AI 발굴 물질 임상 성과 (생명공학연구원 이슈페이퍼는 BioIN 로그인 필요, 받으면 자동 포함) |
| 시장·사업화 | `"market"` | BIO 임상 단계별 성공률, 기술특례상장 제도 개선 방안 |

## 3. 돌려받는 값: `list[RagHit]`

| 필드 | 내용 |
|---|---|
| `chunk_id` | `문서파일#청크번호` |
| `doc` | 문서 제목 (REFERENCE · Evidence.source에 쓴다) |
| `page` | 쪽 번호 (인용용, 사람 기준 1부터) |
| `text` | 청크 원문. 표 · 그림은 `[표·그림]` 아래 비전 전사본 — **인용할 표 수치는 원문 대조** |
| `score` | FAISS 코사인 유사도 (0~1) |

- **관련 문서가 없으면 `[]`.** 웹 보강은 에이전트가 판단한다 (계약대로).
- RAG 문서에는 특정 기업 이야기가 없다. 판단 기준 · 제도 · 통계만 있다. 기업 사실은 웹에서 찾는다.
- RagHit → Evidence 변환은 에이전트가 한다 (`status="확인됨"`, `source=doc`, `page=page`).
- 도구 호출 방식 에이전트라면: `tools=[make_rag_tool("regulation")]`

## 4. 흐름과 설정

```
질문 생성(한국어 + 영어) → FAISS 검색(doc_type 필터) → 관련성 채점
   ├ 관련 있음            → RagHit 반환
   ├ 관련 없음, 재작성 전 → 질문 다시 쓰기 → 다시 검색
   └ 관련 없음, 재작성 후 → []
```

청킹 · 임베딩 · 검색 방식은 실험으로 정한다: `python -m rag.experiment` → `data/eval/best_config.json` → 자동 적용.
현재: **청킹 r500 · bge-m3 · FAISS** (30문항 MRR 0.78, Hit@3 0.83). 전체 표는 `data/eval/results.md`.

## 5. 파일

| 파일 | 역할 |
|---|---|
| `sources.py` | 문서 목록 · 출처 · doc_type |
| `download_docs.py` | 공식 출처에서 PDF 받기 |
| `parse_pdfs.py` | 쪽 단위 추출 → 편집 흔적만 정제(정보는 버리지 않음) → 청크 (r500 · r1000 · r1500 · page) |
| `vision.py` | 표 · 그래프 · 이미지 쪽을 비전 LLM으로 전사 (캐시) |
| `settings.py` | 청킹 · 임베딩 · 검색 방식 기본값 (실험 결과) |
| `experiment.py` | 청킹 × 임베딩 × 검색 비교 → 최적 설정 저장 |
| `build_index.py` | 임베딩 → FAISS 저장 (`data/index/`) |
| `retriever.py` | `get_retriever(doc_type, mode)` — bm25 · faiss · ensemble |
| `rag_search.py` | 에이전트용 Agentic RAG (`rag_search` → `list[RagHit]`, `make_rag_tool`) |
| `eval_retriever.py` | Hit Rate@K · MRR (`data/eval/questions.jsonl`) |
| `prepare.py` | 받기 → 파싱 → 인덱스 한 번에 |
