"""정책값. 팀 합의 후 여기서만 바꾼다."""
from datetime import date

# 후보 4곳 — 평가 순서대로. company_id는 영문 소문자(팀 확정 필요)
CANDIDATES = [
    {"company_id": "standigm", "name": "스탠다임"},
    {"company_id": "diagen", "name": "디어젠"},
    {"company_id": "galux", "name": "갤럭스"},
    {"company_id": "drnoah", "name": "닥터노아바이오텍"},
]

# 12항목: 코드명 -> (한글명, 조사 영역, 관문 여부)
ITEMS = {
    "management":  ("경영진", "company", False),
    "funding":     ("자금 조달", "company", False),
    "reputation":  ("평판", "company", False),
    "stage":       ("사업 단계", "tech", False),
    "manufacturing": ("제조", "tech", False),
    "technology":  ("기술", "tech", True),
    "regulation":  ("법률·정책", "regulation", True),
    "litigation":  ("소송", "regulation", False),
    "overseas":    ("해외", "regulation", False),
    "sales":       ("영업·마케팅", "market", False),
    "competition": ("경쟁", "market", False),
    "exit":        ("투자금 회수", "market", False),
}
AREAS = ("company", "tech", "regulation", "market")
GATE_ITEMS = tuple(k for k, v in ITEMS.items() if v[2])

# 판정 기준
VERDICT_THRESHOLD = 5          # 합계 +5 이상이면 적격 후보
SENSITIVITY_THRESHOLDS = (4, 6)
FUNDING_WINDOW_YEARS = 2

# RAG
DOC_TYPES = ("regulation", "tech", "market")

def today() -> str:
    return date.today().isoformat()

# 투자 판단 LLM
JUDGE_MODEL = "gpt-4.1-mini"
JUDGE_PROVIDER = "openai"
