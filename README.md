# AI Startup Investment Evaluation Agent — Multi-Agent Orchestration
6조 : 김윤성, 정문기, 이승호, 이세영, 이준영

AI 신약개발(Healthcare AI) 스타트업 4곳의 공개 근거를 기업 · 기술 · 규제 · 시장 관점에서 조사하고 투자 위험을 평가하는 에이전트를 Supervisor 패턴으로 설계했다. 설계 근거 · 운영 기준 · 의사결정 기록 등 자세한 내용은 [docs/details.md](docs/details.md)에 있다.

## Overview

- Objective : 4곳의 12개 위험요인 점수와 적격 · 보류 · 부적격 판정을 내고, 최대 10쪽의 통합 보고서 1부를 만든다.
- Pattern : Supervisor - RAG 버전은 고정 검색어로 한 번만 조사해 48칸 중 45칸이 근거 부족으로 끝났다. 무엇이 부족할지는 조사해 봐야 알 수 있어, 미리 계획을 세우는 Orchestrator-Workers 대신 조사 결과를 보고 부족한 영역만 재조사시키는 Supervisor를 골랐다.
- 동적 처리 : 고정된 `select → (company ∥ tech) → (regulation ∥ market) → judge` 대신 `supervisor ⇄ 워커` 구조에서 State의 영역별 근거 · 조사 상태 · 재작업 횟수에 따라 다음 담당과 재작업을 정한다.

## Selected Companies

- Domain : Healthcare AI · AI 신약개발 — 임상 단계 · 임상시험계획 승인 · 기술이전 계약 같은 판단 근거를 공시 · 보도로 확인할 수 있다.
- 선정 기준 : 비상장 · Seed~Series C · Exit 없음을 확인한 AI 신약개발 스타트업 4곳이다.
- 스탠다임 : AI 신약 타깃 발굴
- 디어젠 : AI 타깃 발굴~물질 최적화
- 갤럭스 : AI 항체 설계
- 닥터노아바이오텍 : AI 복합신약

## Features

- 근거 수집 : 웹 검색 → 원문 수집 → LLM 추출 → 인용 검증을 수행하고, Agentic RAG로 찾은 기준 문서는 추출 문맥으로 쓴다.
- 근거 충분성 루프 : 관문 2항목과 4영역의 독립 출처 확인 여부를 검사하고, 부족한 항목을 기업당 2회 · 영역당 1회까지 재조사한다.
- 확증 편향 방지 전략 : 긍정 여부 대신 독립 출처 확인을 기준으로 삼고, 위험 방향 검색어를 추가하며, 출처 편중과 미확인 · 부정 항목을 보고서 한계점에 공개한다.
- 보고서 품질 평가 : 규칙 + LLM Judge Hybrid로 Groundedness · 중립성 · 편향 통제 · 형식을 평가하고, 미달 시 지적 문장만 최대 2회 재작성해 다시 평가한다.

## Tech Stack

- Framework : LangGraph 1.0(StateGraph, add_conditional_edges, SQLite checkpointer)과 LangChain을 쓴다.
- LLM/Supervisor : gpt-4.1-mini의 구조화 출력으로 다음 담당 · 사유 · 재작업 검색어를 선택한다.
- LLM/Generator : gpt-4.1-mini로 원문 추출, 보고서 판단 요지 생성 · 중립 재작성을 수행한다.
- LLM/Judge : gpt-4.1-mini로 12항목 예/아니오를 판단하고 점수는 코드로 계산하며, 보고서 품질 평가는 생성 모델과 분리한 gpt-4.1로 수행한다.
- Retrieval : FAISS를 쓰며, 평가셋 34문항의 Hit Rate@3은 0.824, MRR은 0.703이다(상세는 main 브랜치 README).
- Embedding : `BAAI/bge-m3`를 쓴다.
- Web : Tavily 검색과 원문 HTML/PDF 수집을 사용하며, 재작업은 `include_domains`로 공식 · 학술 출처를 우선한다.
- Tracing : LangSmith의 `metadata.trace_id`로 실행을 추적한다.
- Test : pytest로 LLM · 네트워크 없이 그래프 흐름 · 재작업 · 종료 · 품질 루프 · 보고서 재생성을 검증한다.
- Runtime : Python 3.11을 사용하며, 테스트 · 제출 실행의 패키지 버전은 `requirements.txt`에 고정했다.

## Agents

- Supervisor (`supervisor`) : 근거 충분성과 허용 행동을 계산한 뒤 LLM이 다음 담당 · 사유 · 검색어를 고르며, 코드는 허용 밖 선택을 교정하고 결정을 기록한다.
- 후보 선택 (`select`) : 다음 기업을 선택하고 기업별 영역 상태 · 재작업 횟수 · 읽은 URL을 초기화한다.
- 기업 조사 (`company`) : 경영진 · 자금 조달 · 평판을 조사한다.
- 기술·파이프라인 (`tech`) : 기술 관문 · 사업 단계 · 제조를 조사하고 물질 · 적응증 · 단계 목록을 만든다.
- 규제 (`regulation`) : supervisor가 `task.pipeline`으로 전달한 물질 목록을 바탕으로 법률·정책 관문 · 소송 · 해외를 조사한다.
- 시장·사업화 (`market`) : 물질 · 적응증 단위로 영업·마케팅 · 경쟁 · 투자금 회수를 조사한다.
- 투자 판단 (`judge`) : LLM이 항목별 예/아니오와 근거 ID를 정하고, 코드가 점수 · 관문 · 판정을 계산한다.
- 보고서 작성 (`report`) : 4곳의 통합 보고서(SUMMARY · 1~5장 · REFERENCE, 10쪽 이하)를 만들고 재작성 시 지적 문장만 수정한다.
- 품질 평가 (`quality`) : Hybrid 평가를 수행하고 코드로 통과 여부를 정한다.

## State Schema

- 제어 vs 페이로드 분리 : `next` · `task` · `area_status` · `rework_count` · `step_count` · `report_revisions` · `status`는 제어에, 조사 · 판정 · 보고 결과는 페이로드에 두며, 워커 입력은 `state.py`의 입력 타입과 `add_node(input_schema=...)`로 제한한다.
- 관측성 위치 : 결정 로그는 `outputs/logs/<trace_id>.jsonl`에 쌓고, State에는 마지막 지시의 `task.reason`만 덮어써 LangSmith 노드 출력에서 사유를 확인한다.
- 지속성 비용 : 원문 · RAG 청크는 State에서 제외하고, 근거는 인용 300자 · 원문 수 상한(`--pages-per-node`, 기본 8) · 재작업 예산으로 제한하며, PDF는 경로만 저장하고 `report_sections`는 덮어쓴다.
- 상관 : `trace_id`로 LangGraph `thread_id`, LangSmith `metadata.trace_id`, 결정 · 실행 로그와 보고서 파일명을 연결한다.
- 재개/복구 : SQLite 체크포인터와 `current_idx` · `area_status` · `rework_count` · `read_urls`로 `--resume <trace_id>`를 지원하고, `--rebuild-report <trace_id>`는 `app.reset_report_stage`로 보고서 단계만 다시 실행하며, 실패 원인은 `errors` · `last_error`에 남긴다.
- 동시 처리 : supervisor가 워커를 하나씩 호출하므로 동시 쓰기는 없으며, 누적 키의 `merge_evidence` · `merge_by_company`로 재작업 · 재개 시 근거와 기업 판정의 중복을 막는다.
- 종료 보장 : 재작업은 기업당 2회 · 영역당 1회, 보고서 재작성은 2회로 제한하고, `max_steps`(60)에 도달하면 필수 마무리 단계로 이동하며 절대 상한 74회와 `recursion_limit`을 둔다.

## Architecture

![graph](docs/graph.png)

## 실행 결과

| 기업 | supervisor가 정한 순서 | 재작업 효과 (기업 전체 확인됨 근거 수 전 → 후 / 기업 전체 근거 수 전 → 후) | 판정 |
|---|---|---|---|
| 스탠다임 | 기술 → 규제 → 기업 → 시장 → 규제(재) → 기술(재) | 규제 1→1 / 21→21; 기술 1→1 / 21→26 | 보류 +9점 |
| 디어젠 | 기술 → 규제 → 기업 → 시장 → 규제(재) → 기술(재) | 규제 1→1 / 25→26; 기술 1→3 / 26→33 | 보류 +11점 |
| 갤럭스 | 기술 → 규제 → 기업 → 시장 → 규제(재) → 기술(재) | 규제 2→2 / 16→18; 기술 2→2 / 18→23 | 보류 +9점 |
| 닥터노아바이오텍 | 기술 → 규제 → 기업 → 시장 → 규제(재) → 기술(재) | 규제 0→0 / 19→19; 기술 0→0 / 19→21 | 보류 +5점 |

- 실행 기록 : `1013-1324-d16d`의 조사 · 판정은 `3687430`, 마지막 보고서 단계는 `cb2e65c`이며, 워커 호출은 조사 · 판정 32회와 마지막 보고서 4회를 합쳐 36회다.
- 재작업 효과 : 재작업 8회 중 확인됨 근거를 늘린 경우는 1회다.
- 최종 결과 : 상태는 `done`, 보고서는 6쪽, 재작성은 1회이며 품질 평가 4개 항목을 모두 통과했다.
- 품질 루프 : report → quality(근거성 9건 · 중립성 15건 미달) → report(지적 문장 재작성) → quality(통과) → FINISH로 종료했다.
- 기록 : 결정 로그 · 실행 로그 · 판별 보고서는 [`docs/run-1013-1324-d16d/`](docs/run-1013-1324-d16d/)에 있다.

## Directory Structure

```
├── agents/
│   ├── supervisor.py          # 충분성 · 허용 행동 · LLM 선택 · 가드 · 결정 로그
│   ├── common.py              # 조사 공통: 검색 · 원문 검증 · 재작업 지시 반영 · 실패 처리
│   ├── select_candidate.py
│   ├── company.py · tech_pipeline.py · regulation.py · market.py
├── judge/                     # 12항목 LLM 예/아니오 → 코드 점수 · 판정
├── report/                    # 통합 보고서 문장 구조 · 재작성 · PDF · REFERENCE
├── quality/evaluator.py       # 품질 평가 (Hybrid)
├── prompts/                   # supervisor · judge · 조사 · 보고서 · 품질 프롬프트
├── rag/ · data/               # Agentic RAG와 문서 풀 (main 브랜치와 동일)
├── tools/                     # 웹 검색 · 원문 수집, Evidence 타입
├── outputs/                   # 보고서 PDF, logs/(결정 · 실행 로그)
├── docs/                     # graph.png, run-<trace_id>/(제출 실행 기록: 결정 로그 · 실행 로그 · 판별 보고서)
├── tests/
├── config.py · state.py · graph.py · app.py
└── README.md
```

## Usage

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

`.env`에 키를 넣는다.

```
OPENAI_API_KEY=...
TAVILY_API_KEY=...
LANGSMITH_API_KEY=...        # 트레이스를 볼 때
LANGSMITH_TRACING=true
```

```bash
python app.py                                        # 전체 실행 (워커당 원문 8쪽 · 검색어당 3개, 약 20분)
python app.py --pages-per-node 4 --urls-per-query 2  # 제출한 실행 결과의 설정 (약 10분)
python app.py --resume <trace_id>                    # 중단된 실행 이어서
python app.py --rebuild-report <trace_id>            # 끝난 실행의 보고서 · 품질 평가 단계만 다시 (조사 · 판정 결과는 그대로)
pytest                                               # LLM 없이 흐름 검증
```

## 한계

- 공개 근거 : 비상장사의 독립 검증 자료가 적어 보류로 끝날 수 있으며, 서로 다른 도메인도 같은 보도자료를 인용할 수 있다.
- 품질 평가 : 생성 모델과 Judge가 같은 회사 모델이라 자기 선호 편향이 남을 수 있고, 판정 재사용으로 첫 평가에서 놓친 문장을 다시 묻지 않는다.
- 인용 범위 : 인용을 300자까지만 저장하므로 수치 외 내용의 근거 확인은 LLM Judge 판정에 기댄다.
- 시장 규모 : 12개 조사 항목에 시장 규모가 없어 따로 검색하지 않았고, 수집한 근거에 수치가 없어 보고서에 '찾지 못함'으로 적었다.
- 원문 접근 : 일부 사이트는 자동 접근을 막아 403, 삭제된 기사는 404로 열리지 않는다. 차단을 우회하지 않고 다음 검색 결과로 넘어간다.

## Contributors

- 김윤성 : RAG 문서 · 검색 파이프라인, 문서 수집 · 전처리, 임베딩 처리, `rag_search` 도구를 담당했으며 기술 · 규제 · 시장 워커의 기준 문서 검색(`rag/`, `data/`)에 쓰인다.
- 이세영 : 투자 판단(judge) · 채점 · 판정 로직과 에이전트 입출력 타입을 담당했으며 `judge/` 노드와 12항목 점수 · 관문 · 판정 규칙에 쓰인다.
- 이승호 : RAG 문서 · 검색 파이프라인(청킹 · 임베딩 비교 실험, 비전 전사), Evidence 형식과 Supervisor 패턴 전환(supervisor · State · 그래프 재설계, 근거 충분성 재작업 루프, 통합 보고서 · 품질 평가 루프, 실행 · 트레이스 검증)을 담당했다.
- 이준영 : RAG 문서 · 검색 파이프라인, 문서 수집 · 전처리, 임베딩 처리, `rag_search` 도구를 담당했으며 기술 · 규제 · 시장 워커의 기준 문서 검색(`rag/`, `data/`)에 쓰인다.
- 정문기 : 조사 에이전트(기업 · 기술 · 규제 · 시장), 웹 원문 수집 · 검증, 보고서 작성 · PDF 생성을 담당했으며 조사 워커와 보고서 노드의 기반(`agents/`, `tools/web.py`, `report/`)에 쓰인다.
