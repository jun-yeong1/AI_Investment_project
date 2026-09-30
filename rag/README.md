# RAG 모듈 — 에이전트 팀 사용법

## 1. 준비 (처음 한 번)

```bash
pip install -r requirements.txt
python -m rag.prepare          # 문서 받기 → 파싱 → bge-m3 인덱스 (첫 실행 때 모델 약 2.3GB 다운로드)
# 표 · 그림 비전 전사는 저장소의 캐시(data/processed/vision/)를 쓰므로 API를 다시 부르지 않는다
```

준비(`rag.prepare`)는 API 키 없이 돈다. 검색(`rag_search`)의 질문 생성 · 관련성 채점에는 `.env`의 `OPENAI_API_KEY`가 필요하다.
원본 PDF 6종은 모두 `data/raw/`에 들어 있다.

## 2. 에이전트에서 쓰기 (계약: `rag/types.py`)

```python
from rag.rag_search import rag_search

hits = rag_search("희귀의약품 지정이 신약 개발 위험에서 어떤 의미인가", "regulation")
# 선택: pipeline=state["pipeline"] 을 주면 검색 질문을 물질 · 적응증 단위로 만든다
```

| 에이전트 | doc_type | 들어 있는 문서 |
|---|---|---|
| 규제 | `"regulation"` | FDA Expedited Programs (신속심사 지정 요건) |
| 기술·파이프라인 | `"tech"` | KISTEP AI 신약 브리프, Jayatunga(2024) AI 발굴 물질 임상 성과, 생명공학연구원 이슈페이퍼(이미지 PDF → 비전 OCR) |
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
현재: **청킹 r500 · bge-m3 · FAISS** (문서 6종 · 평가 34문항 · 청킹 5 × 임베딩 3 × 검색 3 비교, MRR 0.703, Hit@3 0.824). 전체 표는 `data/eval/results.md`.

## 5. 파일

| 파일 | 역할 |
|---|---|
| `sources.py` | 문서 목록 · 출처 · doc_type |
| `download_docs.py` | 공식 출처에서 PDF 받기 |
| `parse_pdfs.py` | 쪽 단위 추출 → 편집 흔적만 정제(정보는 버리지 않음) → 청크 (r500 · r1000 · r1500 · page · struct) |
| `vision.py` | 표 · 그래프 · 이미지 쪽을 비전 LLM(gpt-4.1-mini)으로 전사. 글자 층을 참고로 주되 이미지 값 우선. 캐시 `data/processed/vision/` |
| `settings.py` | 청킹 · 임베딩 · 검색 방식 기본값 (실험 결과) |
| `experiment.py` | 청킹 5종 × 임베딩 3종 × 검색 3종 비교 → 최적 설정 저장 (`results.md`, `best_config.json`) |
| `build_index.py` | 임베딩 → FAISS 저장 (`data/index/`) |
| `retriever.py` | `get_retriever(doc_type, mode)` — bm25 · faiss · ensemble |
| `rag_search.py` | 에이전트용 Agentic RAG (`rag_search` → `list[RagHit]`, `make_rag_tool`) |
| `eval_retriever.py` | Hit Rate@K · MRR (`data/eval/questions.jsonl`) |
| `prepare.py` | 받기 → 파싱 → 인덱스 한 번에 |

## 6. 텍스트화에서 알게 된 것

- **정보는 버리지 않는다.** 지우는 것은 줄번호 · 쪽번호 · 반복 머리말의 중복뿐. 표 숫자 · 목차 · 참고문헌은 남긴다.
- **표 · 그림은 비전 LLM으로 전사한다.** 글자 추출만으로는 차트 값과 표의 행 · 열 관계가 흩어진다 (BIO 보고서 글자 +30%).
- **이미지로만 된 PDF**(생명공학연구원 이슈페이퍼, BioIN 뷰어 인쇄본 29쪽)는 쪽 전체를 비전으로 옮긴다. gpt-4o-mini는 수치 · 제목을 잘못 읽어 gpt-4.1-mini + 300dpi로 바꿨다.
- **글자 층도 틀릴 수 있다.** 기술특례상장 4쪽 표의 "1개 / 0.7%"가 강조 테두리와 겹쳐 글자 층에서는 "111개 / 10.7%"로 추출됐다. 그래서 비전에게 글자 층을 참고로 주되 이미지에서 보이는 값을 우선하게 했다.
- **비전 폭주 출력**: 기술특례상장 14쪽에서 모델이 표 구분선을 210만 자 이어 썼다 → `max_tokens` 제한, 기호 반복 정리, 12,000자 초과 자르기, 파싱 단계에서 한 쪽 2만 자 초과 시 중단. Kiwi 토큰화 전에도 기호열을 지운다.
- 보고서에 인용하는 표 수치는 원문 PDF와 대조한다.
