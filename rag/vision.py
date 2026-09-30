"""표 · 그래프 · 그림을 텍스트로 옮긴다 — PDF 쪽을 이미지로 바꿔 비전 LLM에게 전사를 맡긴다.

글자 추출(PyMuPDF)로는 차트의 막대 값, 표의 행 · 열 관계, 이미지 속 글자가 흩어지거나 빠진다.
그래서 쪽마다 이미지로 렌더링해 "표 · 그림 속 정보만" 옮기게 하고, 본문 글자와 합친다.
결과는 data/processed/vision/ 에 캐시해 다시 돌려도 LLM을 또 부르지 않는다.
"""
import base64
import re
from pathlib import Path

from langchain_core.messages import HumanMessage

from rag import settings

ROOT = Path(__file__).resolve().parents[1]
CACHE_DIR = ROOT / "data" / "processed" / "vision"
NONE = "없음"

PROMPT = f"""이 이미지는 PDF 문서의 한 쪽이다. 표 · 그래프 · 차트 · 다이어그램 · 그림 · 이미지 안의 정보를 빠짐없이 텍스트로 옮겨라.
- 표: 마크다운 표로. 행 · 열 제목과 모든 값을 그대로.
- 그래프 · 차트: 제목, 축 이름, 단위, 그리고 막대 · 점마다 "라벨: 값"으로 모두.
- 다이어그램 · 흐름도: 상자 안 글자와 화살표 순서를 "A → B" 형태로.
- 이미지 속 글자(표지 제목, 로고 옆 문구 등)도 옮긴다.
- 쪽의 일반 본문 문단은 옮기지 않는다 (따로 추출한다).
- 원문 언어 그대로 쓰고, 추측해서 값을 만들지 않는다. 읽을 수 없는 값은 [판독 불가]로 쓴다.
- 표 · 그래프 · 그림이 전혀 없으면 "{NONE}" 한 단어만 출력한다."""


def _render(pdf_path: Path, page_no: int, dpi: int = 150) -> str:
    import pymupdf
    with pymupdf.open(pdf_path) as pdf:
        pix = pdf[page_no - 1].get_pixmap(dpi=dpi)
        return base64.b64encode(pix.tobytes("png")).decode()


FULL_PROMPT = """이 이미지는 PDF 문서의 한 쪽이며, 글자가 이미지로만 되어 있다.
쪽에 보이는 모든 글자를 위에서 아래 순서로 빠짐없이 옮겨라. 표는 마크다운 표로 옮긴다.
원문 언어 그대로 쓰고, 추측해서 만들지 않는다. 읽을 수 없는 글자는 [판독 불가]로 쓴다."""


def describe_page(pdf_path: Path, page_no: int, full: bool = False) -> str:
    """page_no는 1부터. 표 · 그림 정보가 없으면 빈 문자열.
    full=True: 글자 추출이 안 되는 쪽(이미지로만 된 쪽) — 쪽의 모든 글자를 옮긴다."""
    cache = CACHE_DIR / f"{pdf_path.stem}_p{page_no:03d}{'_full' if full else ''}.md"
    if cache.exists():
        text = cache.read_text(encoding="utf-8")
    else:
        from langchain.chat_models import init_chat_model
        llm = init_chat_model(settings.VISION_MODEL, temperature=0)
        msg = HumanMessage(content=[
            {"type": "text", "text": FULL_PROMPT if full else PROMPT},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{_render(pdf_path, page_no, 300 if full else 150)}",
                                                "detail": "high"}},
        ])
        text = llm.invoke([msg]).content.strip()
        text = re.sub(r"^```[a-z]*\n?|\n?```$", "", text).strip()   # 코드 블록 표시 제거
        text = re.sub(r"(^.*\[판독 불가\].*$\n?){2,}", "[판독 불가 — 그림 속 작은 글자]\n", text, flags=re.M)  # 반복 줄 하나로
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache.write_text(text, encoding="utf-8")
    return "" if text.strip() == NONE else text
