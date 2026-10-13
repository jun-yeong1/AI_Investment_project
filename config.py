"""정책값. 팀 합의 후 여기서만 바꾼다."""
from datetime import date

# 후보 4곳 — 평가 순서대로. company_id는 영문 소문자(팀 확정 필요)
CANDIDATES = [
    {"company_id": "standigm", "name": "스탠다임", "en": "Standigm"},
    {"company_id": "diagen", "name": "디어젠", "en": "Deargen"},
    {"company_id": "galux", "name": "갤럭스", "en": "Galux"},
    {"company_id": "drnoah", "name": "닥터노아바이오텍", "en": "Dr. Noah Biotech"},
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

# Supervisor — 근거 충분성 루프와 종료 상한
SUPERVISOR_MODEL = "gpt-4.1-mini"
MAX_REWORK_PER_AREA = 1        # 영역별 재작업 상한. 같은 영역을 같은 방식으로 반복해도 결과가 잘 안 바뀐다
MAX_REWORK_PER_COMPANY = 2     # 기업당 재작업 예산 = 관문 2개(기술, 법률·정책)에 한 번씩. 어디에 쓸지는 supervisor가 고른다
MAX_STEPS = 60                 # 워커 호출 수 상한. 기업당 최대 8단계(선택 1 + 조사 4 + 재작업 2 + 판정 1) x 4 + 보고서 · 품질 루프 6
MAX_REPORT_REVISIONS = 2       # 품질 평가 미달 시 보고서 재작성 상한
MAX_REPORT_PAGES = 10
