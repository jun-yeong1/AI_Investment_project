"""RAG 문서 목록. 파일 이름 · doc_type · 출처 정보를 한곳에서 관리한다.

- committed=True : 저장소에 PDF를 포함한다 (FDA = 미국 정부 문서, Jayatunga = CC BY-NC-ND, BIO = 공식 주소 404 대비)
- url 이 있는 문서 : rag/download_docs.py 가 공식 출처에서 받는다
- optional=True  : 없어도 파이프라인이 돈다 (로그인이 필요해 자동으로 받을 수 없는 문서)
"""

from config import DOC_TYPES  # ("regulation", "tech", "market") — 팀 공통 설정

DOCS = {
    "regulation_FDA_expedited_programs_2014.pdf": {
        "doc_type": "regulation", "lang": "en", "year": 2014, "committed": True,
        "publisher": "U.S. Food and Drug Administration",
        "title": "Expedited Programs for Serious Conditions – Drugs and Biologics (Guidance for Industry)",
        "source_url": "https://www.fda.gov/media/86377/download",
    },
    "tech_KISTEP_AI_drug_brief_2025.pdf": {
        "doc_type": "tech", "lang": "ko", "year": 2025,
        "publisher": "한국과학기술기획평가원",
        "title": "AI를 활용한 혁신 신약개발의 동향 및 정책 시사점",
        "source_url": "https://www.kistep.re.kr/boardDownload.es?bid=0031&list_no=94091&seq=1",
        "url": "https://www.kistep.re.kr/boardDownload.es?bid=0031&list_no=94091&seq=1",
    },
    "tech_Jayatunga_AI_drugs_clinical_2024.pdf": {
        "doc_type": "tech", "lang": "en", "year": 2024, "committed": True,
        "publisher": "Drug Discovery Today",
        "title": "How successful are AI-discovered drugs in clinical trials? A first analysis and emerging lessons",
        "source_url": "https://doi.org/10.1016/j.drudis.2024.104009",
    },
    "tech_KRIBB_AI_drug_issue_paper_2025.pdf": {
        "doc_type": "tech", "lang": "ko", "year": 2025, "optional": True,
        "publisher": "한국생명공학연구원 첨단바이오 국가기술전략센터",
        "title": "AI신약개발 분야 기술경쟁력 및 정부 R&D 투자현황 분석",
        "source_url": "https://www.bioin.or.kr/board.do?num=330782&cmd=view&bid=report",
    },
    "market_BIO_clinical_success_rates_2021.pdf": {
        "doc_type": "market", "lang": "en", "year": 2021, "committed": True,   # 공식 주소가 막힐 때가 있어 저장소에 포함
        "publisher": "BIO, Informa Pharma Intelligence, QLS Advisors",
        "title": "Clinical Development Success Rates and Contributing Factors 2011–2020",
        "source_url": "https://go.bio.org/rs/490-EHZ-999/images/ClinicalDevelopmentSuccessRates2011_2020.pdf",
        "url": "https://go.bio.org/rs/490-EHZ-999/images/ClinicalDevelopmentSuccessRates2011_2020.pdf",
    },
    "market_FSC_tech_listing_reform_2023.pdf": {
        "doc_type": "market", "lang": "ko", "year": 2023,
        "publisher": "관계기관 합동",
        "title": "기술특례상장 제도 개선 방안",
        "source_url": "https://www.fsc.go.kr/no010101/80493",
        "url": "https://fsc.go.kr/comm/getFile?fileNo=7&fileTy=ATTACH&srvcId=BBSTY1&upperNo=80493",
    },
}


def doc_meta(filename: str) -> dict:
    """청크 메타데이터에 붙일 값 (다운로드용 키는 뺀다)."""
    info = DOCS[filename]
    return {k: info[k] for k in ("doc_type", "lang", "year", "publisher", "title", "source_url")}
