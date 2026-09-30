"""후보 4곳 조사·판정 후 PDF를 병합하고 감사용 JSON을 남긴다.

실행: python app.py
빠른 실연: python app.py --pages-per-node 1 --urls-per-query 1
"""

from __future__ import annotations

import argparse
import copy
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from config import CANDIDATES
from graph import build_graph
from report.pdf import finalize_reports

ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = ROOT / "outputs"


def _positive_int(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("1 이상의 정수를 입력하세요")
    return number


def _save_log(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str),
                         encoding="utf-8")
    temporary.replace(path)


def run(*, output: Path, log_path: Path) -> dict[str, Any]:
    """그래프 상태를 스트리밍해 기업별 점수를 보존하고 최종 PDF를 만든다."""
    initial = {
        "candidates": [dict(candidate) for candidate in CANDIDATES],
        "current_idx": -1,
        "evidence": [],
        "evaluations": [],
        "reports": [],
    }
    started_at = datetime.now().astimezone().isoformat()
    record: dict[str, Any] = {
        "status": "running",
        "started_at": started_at,
        "candidates": initial["candidates"],
        "evaluations": [],
        "scores_by_company": {},
        "evidence": [],
        "reports": [],
    }
    _save_log(log_path, record)
    final_state = None
    try:
        for snapshot in build_graph().stream(initial, stream_mode="values"):
            final_state = snapshot
            known = record["scores_by_company"]
            for evaluation in snapshot.get("evaluations", []):
                company_id = evaluation["company_id"]
                if company_id not in known:
                    known[company_id] = copy.deepcopy(snapshot.get("scores", {}))
                    print(f"평가 완료: {evaluation['name']} — {evaluation['verdict']} "
                          f"({evaluation['total']:+d}점)", flush=True)
                    record["evaluations"] = copy.deepcopy(snapshot["evaluations"])
                    record["evidence"] = copy.deepcopy(snapshot.get("evidence", []))
                    record["reports"] = list(snapshot.get("reports", []))
                    _save_log(log_path, record)

        if final_state is None:
            raise RuntimeError("그래프가 상태를 반환하지 않았습니다")
        if len(record["scores_by_company"]) != len(CANDIDATES):
            raise RuntimeError("모든 후보의 투자 판단이 완료되지 않았습니다")
        merged = finalize_reports(final_state, output)
        record.update(
            status="complete",
            finished_at=datetime.now().astimezone().isoformat(),
            evaluations=final_state.get("evaluations", []),
            evidence=final_state.get("evidence", []),
            reports=final_state.get("reports", []),
            merged_report=str(merged),
        )
        _save_log(log_path, record)
        return record
    except Exception as exc:
        record.update(status="failed", finished_at=datetime.now().astimezone().isoformat(),
                      error=f"{type(exc).__name__}: {exc}")
        if final_state is not None:
            record["evaluations"] = final_state.get("evaluations", [])
            record["evidence"] = final_state.get("evidence", [])
            record["reports"] = final_state.get("reports", [])
        _save_log(log_path, record)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AI 신약개발 스타트업 투자 보고서 생성")
    parser.add_argument("--output", type=Path, default=OUTPUT_DIR / "investment_reports.pdf",
                        help="병합된 보고서 PDF 경로")
    parser.add_argument("--log", type=Path, default=OUTPUT_DIR / "investment_run.json",
                        help="근거·기업별 점수 JSON 경로")
    parser.add_argument("--pages-per-node", type=_positive_int,
                        help="조사 노드별 원문 페이지 수 제한 (기본값은 Agent 설정)")
    parser.add_argument("--urls-per-query", type=_positive_int,
                        help="검색 질문별 URL 수 제한 (기본값은 Agent 설정)")
    args = parser.parse_args(argv)

    load_dotenv(ROOT / ".env")
    if args.pages_per_node is not None:
        os.environ["AGENT_PAGES_PER_NODE"] = str(args.pages_per_node)
    if args.urls_per_query is not None:
        os.environ["AGENT_URLS_PER_QUERY"] = str(args.urls_per_query)

    record = run(output=args.output, log_path=args.log)
    print(f"병합 보고서: {record['merged_report']}")
    print(f"실행 로그: {args.log}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
