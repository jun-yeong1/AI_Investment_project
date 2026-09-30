"""RAG 기본 설정. 실험(python -m rag.experiment)이 고른 최적 조합을 data/eval/best_config.json에 저장하면
그 값을 쓴다. 환경변수로 덮어쓸 수 있다: RAG_CHUNK, RAG_MODEL, RAG_SEARCH_MODE, RAG_LLM_MODEL
"""
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BEST_CONFIG = ROOT / "data" / "eval" / "best_config.json"

_best = json.loads(BEST_CONFIG.read_text(encoding="utf-8")) if BEST_CONFIG.exists() else {}

CHUNK = os.getenv("RAG_CHUNK", _best.get("chunk", "r1000"))
MODEL = os.getenv("RAG_MODEL", _best.get("model", "bge-m3"))
SEARCH_MODE = os.getenv("RAG_SEARCH_MODE", _best.get("mode", "ensemble"))
LLM_MODEL = os.getenv("RAG_LLM_MODEL", "gpt-4o-mini")
VISION_MODEL = os.getenv("RAG_VISION_MODEL", "gpt-4.1-mini")   # 이미지 PDF 인식에서 4o-mini보다 정확 (KRIBB 6쪽 비교)
