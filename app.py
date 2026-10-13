"""후보 4곳을 Supervisor 그래프로 조사 · 판정하고 통합 보고서 1부를 만든다.

실행: python app.py
빠른 실연: python app.py --pages-per-node 1 --urls-per-query 1
중단된 실행 이어서: python app.py --resume <trace_id>
"""

from __future__ import annotations

import argparse
import json
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from config import CANDIDATES, MAX_STEPS
from graph import build_graph

ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = ROOT / "outputs"
LOG_DIR = OUTPUT_DIR / "logs"
CHECKPOINT_DB = OUTPUT_DIR / "checkpoints.sqlite"


def _positive_int(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("1 이상의 정수를 입력하세요")
    return number


def _save_log(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    temporary.replace(path)


def initial_state(trace_id: str) -> dict[str, Any]:
    return {
        "trace_id": trace_id,
        "candidates": [dict(candidate) for candidate in CANDIDATES],
        "current_idx": -1,
        "evidence": [],
        "evaluations": [],
        "errors": [],
        "step_count": 0,
        "max_steps": MAX_STEPS,
        "report_revisions": 0,
        "status": "running",
    }


def _progress(update: dict[str, Any]) -> None:
    """supervisor 결정과 판정을 터미널에 한 줄씩 보여 준다. 전체 결정 로그는 logs/<trace_id>.jsonl."""
    for node, change in update.items():
        if not isinstance(change, dict):
            continue
        if node == "supervisor" and change.get("next"):
            task = change.get("task") or {}
            mode = " (재작업)" if task.get("mode") == "rework" else ""
            print(f"[supervisor] → {change['next']}{mode}: {task.get('reason', '')}", flush=True)
        for evaluation in change.get("evaluations", []) if node == "judge" else []:
            print(f"  판정: {evaluation['name']} — {evaluation['verdict']} ({evaluation['total']:+d}점)", flush=True)
        if node == "quality" and change.get("quality"):
            quality = change["quality"]
            print(f"  품질 평가: {'통과' if quality['passed'] else '미달'} — {quality.get('summary', '')}", flush=True)


def run(trace_id: str, *, resume: bool) -> dict[str, Any]:
    from langgraph.checkpoint.sqlite import SqliteSaver

    config = {
        "configurable": {"thread_id": trace_id},
        "run_name": "investment-supervisor",
        "metadata": {"trace_id": trace_id},
        "tags": ["supervisor", trace_id],
    }
    log_path = LOG_DIR / f"{trace_id}.json"
    record: dict[str, Any] = {"trace_id": trace_id, "status": "running",
                              "started_at": datetime.now().astimezone().isoformat()}
    _save_log(log_path, record)
    CHECKPOINT_DB.parent.mkdir(parents=True, exist_ok=True)
    with SqliteSaver.from_conn_string(str(CHECKPOINT_DB)) as checkpointer:
        graph = build_graph(checkpointer=checkpointer)
        try:
            # resume이면 입력 없이 마지막 체크포인트에서 이어 간다
            for update in graph.stream(None if resume else initial_state(trace_id), config,
                                       stream_mode="updates"):
                _progress(update)
            final = graph.get_state(config).values
        except Exception as exc:
            record.update(status="failed", error=f"{type(exc).__name__}: {exc}",
                          finished_at=datetime.now().astimezone().isoformat())
            _save_log(log_path, record)
            print(f"실패: {exc}\n이어서 실행: python app.py --resume {trace_id}")
            raise

    record.update(
        status=final.get("status", "unknown"),
        finished_at=datetime.now().astimezone().isoformat(),
        steps=final.get("step_count"),
        report=final.get("report_path"),
        report_pages=final.get("report_pages"),
        report_revisions=final.get("report_revisions"),
        quality=final.get("quality"),
        report_changes=(final.get("report_sections") or {}).get("changes", []),
        evaluations=final.get("evaluations", []),
        errors=final.get("errors", []),
        evidence=final.get("evidence", []),
    )
    _save_log(log_path, record)
    return record


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AI 신약개발 스타트업 투자 보고서 생성 (Supervisor)")
    parser.add_argument("--resume", metavar="TRACE_ID", help="중단된 실행을 마지막 체크포인트부터 이어서 실행")
    parser.add_argument("--pages-per-node", type=_positive_int,
                        help="조사 워커 1회당 원문 페이지 수 제한 (기본값은 Agent 설정)")
    parser.add_argument("--urls-per-query", type=_positive_int,
                        help="검색어별 URL 수 제한 (기본값은 Agent 설정)")
    args = parser.parse_args(argv)

    load_dotenv(ROOT / ".env")
    missing = [key for key in ("OPENAI_API_KEY", "TAVILY_API_KEY") if not os.getenv(key)]
    if missing:
        # 키가 없으면 조사 워커가 전부 실패한 채 빈 보고서가 나오므로 시작 전에 멈춘다
        print(f".env에 {', '.join(missing)}가 없습니다")
        return 1
    if args.pages_per_node is not None:
        os.environ["AGENT_PAGES_PER_NODE"] = str(args.pages_per_node)
    if args.urls_per_query is not None:
        os.environ["AGENT_URLS_PER_QUERY"] = str(args.urls_per_query)

    trace_id = args.resume or datetime.now().strftime("%m%d-%H%M-") + uuid.uuid4().hex[:4]
    print(f"trace_id: {trace_id}")
    record = run(trace_id, resume=bool(args.resume))
    print(f"상태: {record['status']} · 워커 호출 {record['steps']}회 · 보고서 재작성 {record['report_revisions']}회")
    print(f"보고서: {record['report']} ({record['report_pages']}쪽)")
    print(f"실행 로그: {LOG_DIR / (trace_id + '.json')} · 결정 로그: {LOG_DIR / (trace_id + '.jsonl')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
