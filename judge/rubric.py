"""12항목 평가표 (최종 설계서 C-1). ① −2 · ② +2 · ③ +1 기준 문구.
관문 · 조사 영역은 config.ITEMS에서 가져온다."""
from config import ITEMS

# 코드명 -> (① −2 확인되면, ② +2 확인됨일 때, ③ +1 일부 · 기업 주장만)
_CRITERIA = {
    "management": (
        "창업진 이력이 공개됐는데 신약 · AI 관련 이력이 없음, 또는 핵심 인력 이탈",
        "창업 전 제약 개발 경력 · 관련 논문 + 창업 후 제약사 출신 핵심 인력 영입",
        "둘 중 하나만",
    ),
    "stage": ("파이프라인이 발굴 단계뿐", "임상 진입(첫 투여)", "전임상 진입"),
    "regulation": (
        "임상 보류(Clinical Hold) · 중단 · 반려",
        "IND 효력 발생(FDA) · 임상시험계획 승인(식약처)",
        "희귀의약품 · 신속심사 지정",
    ),
    "manufacturing": ("생산 · 품질 문제 보도", "GMP 위탁생산(CDMO) 계약", "CDMO 협의 · MOU"),
    "sales": ("파트너 계약 해지", "기술이전 계약(계약금 공개)", "공동연구 · MOU"),
    "funding": ("자금난 · 구조조정 보도", "최근 2년 안 후속 투자 유치", "그 이전 투자만 확인"),
    "competition": (
        "제3자 분석에서 차별점 없음",
        "자체 데이터 · 특허 · 실험 검증 중 2개 이상",
        "1개만",
    ),
    "technology": (
        "AI 발굴 물질의 임상 실패 · 개발 중단 · 논문 철회",
        "전임상 · 임상 결과 데이터를 동료심사 논문으로 공개",
        "학회 발표 · 비심사 자료",
    ),
    "litigation": ("특허 분쟁 · 소송 진행", "핵심 특허 등록, 분쟁 없음", "특허 출원만"),
    "overseas": (
        "해외 임상 실패 · 해외 계약 해지",
        "해외 기술이전 · 해외 임상 진행",
        "해외 공동연구 · MOU",
    ),
    "reputation": (
        "연구 부정 · 부정 보도",
        "정부 과제 선정 · 공신력 있는 수상",
        "긍정 보도 · 소규모 수상",
    ),
    "exit": (
        "상장 철회 · 기술성평가 탈락 반복",
        "기술성평가 통과 · 상장 예비심사 청구",
        "상장 주관사 선정 · 상장 추진 공개",
    ),
}

RUBRIC = {
    code: {
        "name": ITEMS[code][0],
        "area": ITEMS[code][1],
        "gate": ITEMS[code][2],
        "neg": neg,
        "pos": pos,
        "partial": partial,
    }
    for code, (neg, pos, partial) in _CRITERIA.items()
}

assert set(RUBRIC) == set(ITEMS), "rubric과 config.ITEMS의 항목이 다르다"
