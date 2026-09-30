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

# RAG 원본 문서 (data/raw). file은 접두어가 아니라 파일명 전체.
# doc = RagHit.doc(문서명), lang = 질문·BM25 토큰화 기준, ocr = 텍스트 층이 없는 스캔본
# line_numbers = 본문 왼쪽 줄번호가 텍스트에 섞여 있는 문서
RAG_SOURCES = [
    {
        "doc_id": "fda-ai-2025",
        "file": "FDA 「Considerations for the Use of AI to Support Regulatory Decision-Making for Drug and Biological Products」(2025).pdf",
        "doc": "FDA Considerations for the Use of AI to Support Regulatory Decision-Making for Drug and Biological Products (2025)",
        "doc_type": "regulation", "lang": "en", "line_numbers": True,
    },
    {
        "doc_id": "kistep-2025",
        "file": "KISTEP 「AI를 활용한 혁신 신약개발의 동향 및 정책 시사점」(2025).pdf",
        "doc": "KISTEP AI를 활용한 혁신 신약개발의 동향 및 정책 시사점 (2025)",
        "doc_type": "tech", "lang": "ko",
    },
    {
        "doc_id": "jayatunga-2024",
        "file": "Jayatunga et al.「How successful are AI-discovered drugs in clinical trials?」(2024).pdf",
        "doc": "Jayatunga et al. How successful are AI-discovered drugs in clinical trials? (2024)",
        "doc_type": "tech", "lang": "en",
    },
    {
        "doc_id": "kribb-2025",
        "file": "AI신약개발.pdf",
        "doc": "한국생명공학연구원 AI신약개발 분야 기술경쟁력 및 정부 R&D 투자현황 분석 (2025)",
        "doc_type": "tech", "lang": "ko", "ocr": True,
    },
    {
        "doc_id": "bio-2021",
        "file": "ClinicalDevelopmentSuccessRates2011_2020.pdf",
        "doc": "BIO Clinical Development Success Rates 2011-2020 (2021)",
        "doc_type": "market", "lang": "en",
    },
    {
        "doc_id": "fsc-2023",
        "file": "230727 (별첨2) 기술특례상장 제도 개선 방안.pdf",
        "doc": "관계기관 합동 기술특례상장 제도 개선 방안 (2023)",
        "doc_type": "market", "lang": "ko",
    },
]

RAG_EMBEDDING_MODEL = "BAAI/bge-m3"   # 평가셋 결과로 최종 확정
RAG_CHUNK_SIZE = 1000                 # 비교 후보: 500 · 1000 · 1500
RAG_CHUNK_OVERLAP = 150
RAG_MIN_CHUNK_CHARS = 30              # 이보다 짧은 청크(머리말 찌꺼기 등)는 버린다
RAG_OCR_MIN_CHARS = 30                # 쪽 텍스트가 이보다 짧으면 OCR로 대체
RAG_OCR_LANG = "kor+eng"
RAG_OCR_DPI = 300
RAG_TOP_K = 5
RAG_MIN_SIMILARITY = 0.55             # dense 코사인 유사도 하한. 미만이면 관련 없음
                                      # (bge-m3 실측: 무관 질문 최대 0.50 · 관련 질문 1위 0.57~0.70)
RAG_FUSION_WEIGHTS = (1.0, 1.0)       # (dense, BM25) RRF 가중치. 평가셋으로 비교 후 확정

def today() -> str:
    return date.today().isoformat()

# 투자 판단 LLM
JUDGE_MODEL = "gpt-4.1-mini"
JUDGE_PROVIDER = "openai"
