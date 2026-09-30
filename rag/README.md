# RAG 모듈 — 에이전트 팀 사용법

## 1. 준비 (처음 한 번)

```bash
pip install -r requirements.txt
python -m rag.prepare          # 문서 받기 → 파싱 → bge-m3 인덱스 (첫 실행 때 모델 약 2.3GB 다운로드)
```

`.env`에 `OPENAI_API_KEY`가 필요하다. `TAVILY_API_KEY`가 있으면 문서에 답이 없을 때 웹 검색으로 보강한다.

## 2. 에이전트에서 쓰기

```python
from rag.rag_search import rag_search

evidence = rag_search(
    "희귀의약품 지정이 신약 개발 위험에서 어떤 의미인가",
    doc_type="규제",
    company="닥터노아바이오텍",
    pipeline=state["pipeline"],   # 기술·파이프라인 에이전트가 찾은 목록 (없으면 생략)
)
```

| 에이전트 | doc_type | 들어 있는 문서 |
|---|---|---|
| 규제 | `"규제"` | FDA Expedited Programs (신속심사 지정 요건) |
| 기술·파이프라인 | `"기술"` | KISTEP AI 신약 브리프, Jayatunga(2024) AI 발굴 물질 임상 성과 |
| 시장·사업화 | `"시장·사업성"` | BIO 임상 단계별 성공률, 기술특례상장 제도 개선 방안 |

- **RAG 문서에는 특정 기업 이야기가 없다.** 판단 기준 · 제도 · 통계만 있다. 기업 사실(투자, 허가, 계약)은 웹 검색으로 찾는다.
- 문서에 답이 없으면 한 번 질문을 바꿔 다시 찾고, 그래도 없으면 웹 검색으로 보강한다. 웹 결과는 기업 이름이 나오는 것만 남긴다.
- 도구 호출 방식 에이전트라면: `tools=[make_rag_tool("규제", company)]`

## 3. 돌려받는 값: `list[Evidence]` (`tools/evidence.py`)

| 필드 | RAG 근거 | 웹 근거 |
|---|---|---|
| `source_type` | `"rag"` | `"web"` |
| `status` | `"확인됨"` (공공기관 · 학술 문서) | `"미분류"` → **에이전트가 출처를 보고 정한다** |
| `title`, `publisher`, `url` | 문서 정보 | 페이지 제목, URL |
| `page` | 쪽 번호 (인용용) | 없음 |
| `quote` | 청크 원문 | 본문 발췌 (최대 1,500자) |
| `fact` | 원문 앞부분 → **에이전트가 근거 한 줄로 고쳐 쓴다** | 같음 |
| `item`, `company` | `item`은 **에이전트가 12항목 중 하나로 채운다** | 같음 |
| `id`, `accessed` | 자동 (REFERENCE 번호 · 접근일) | 같음 |

## 4. 흐름 (설계서 B-2)

```
질문 생성(한국어 + 영어) → 하이브리드 검색(Kiwi BM25 + bge-m3 FAISS, doc_type 필터) → 관련성 채점
   ├ 관련 있음            → 근거 기록
   ├ 관련 없음, 재작성 전 → 질문 다시 쓰기 → 다시 검색
   └ 관련 없음, 재작성 후 → 웹 검색 보강
```

## 5. 파일

| 파일 | 역할 |
|---|---|
| `sources.py` | 문서 목록 · 출처 · doc_type |
| `download_docs.py` | 공식 출처에서 PDF 받기 |
| `parse_pdfs.py` | 쪽 단위 추출 → 머리말 · 줄번호 · 합자 정제 → 청크(기본 1000자, 문자 기준) |
| `build_index.py` | 임베딩 → FAISS 저장 (`data/index/`) |
| `retriever.py` | `get_retriever(doc_type, mode)` — bm25 · faiss · ensemble |
| `rag_search.py` | 에이전트용 Agentic RAG (`rag_search`, `make_rag_tool`) |
| `eval_retriever.py` | Hit Rate@K · MRR (`data/eval/questions.jsonl`) |
| `prepare.py` | 받기 → 파싱 → 인덱스 한 번에 |

## 6. 웹 검색 연결 규칙

`tools/web.py`에 `web_search(query, k)`가 생기면 `rag_search`는 자동으로 그걸 쓴다. 반환 형식을 맞춰 주세요.

```python
def web_search(query: str, k: int = 3) -> list[dict]:
    # [{"title": str, "url": str, "content": 본문 발췌, "published": "YYYY-MM-DD" 또는 ""}]
```
