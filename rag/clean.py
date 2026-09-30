"""쪽 텍스트 정제: 반복 머리말·꼬리말, 쪽번호, 줄번호, 합자, 하이픈 줄바꿈."""
import re
import unicodedata
from collections import Counter

_PAGE_MARK = re.compile(r"^\s*[-–]\s*\d+\s*[-–]\s*$")   # "- 4 -"
_DIGITS_ONLY = re.compile(r"^\s*\d{1,4}\s*$")
_WORD_LINE = re.compile(r"^[A-Za-z][A-Za-z’',.;:()\-]*$")   # 낱말 하나뿐인 줄
_MIN_WORD_RUN = 3        # 낱말 줄이 이만큼 이어지면 한 줄로 합친다
_EDGE_LINES = 3          # 쪽 위·아래에서 머리말·꼬리말 후보로 볼 줄 수
_REPEAT_RATIO = 0.4      # 이 비율 이상의 쪽에서 반복되면 머리말·꼬리말
_MIN_PAGES = 3           # 쪽이 너무 적으면 반복 판정이 불안정하다


def _norm(line: str) -> str:
    return re.sub(r"\d+", "#", line.strip())


def find_repeated_lines(pages: list[str]) -> set[str]:
    """쪽 위·아래에서 자주 반복되는 줄(숫자는 #으로 치환)을 찾는다."""
    if len(pages) < _MIN_PAGES:
        return set()
    counter: Counter[str] = Counter()
    for text in pages:
        lines = [ln for ln in text.split("\n") if ln.strip()]
        edge = {_norm(ln) for ln in lines[:_EDGE_LINES] + lines[-_EDGE_LINES:]}
        counter.update(edge)
    limit = len(pages) * _REPEAT_RATIO
    return {k for k, v in counter.items() if v >= limit and len(k) < 120}


def _join_word_runs(text: str) -> str:
    """양쪽 정렬 본문에서 낱말이 한 줄씩 끊겨 추출된 구간을 한 줄로 잇는다."""
    out: list[str] = []
    run: list[str] = []

    def flush():
        if len(run) >= _MIN_WORD_RUN:
            out.append(" ".join(run))
        else:
            out.extend(run)
        run.clear()

    for ln in text.split("\n"):
        if _WORD_LINE.match(ln.strip()):
            run.append(ln.strip())
        else:
            flush()
            out.append(ln)
    flush()
    return "\n".join(out)


def clean_pages(pages: list[str], line_numbers: bool = False) -> list[str]:
    """쪽 번호를 보존한 채(리스트 순서 = 쪽) 각 쪽의 텍스트를 정제한다.

    line_numbers=True: 본문 왼쪽 줄번호가 별도 줄로 섞인 문서(숫자만 있는 줄을 지운다).
    """
    repeated = find_repeated_lines(pages)
    out = []
    for text in pages:
        text = unicodedata.normalize("NFKC", text)   # ﬁ → fi 등 합자·호환 문자
        lines = text.split("\n")
        nonempty = [i for i, ln in enumerate(lines) if ln.strip()]
        edge_idx = set(nonempty[:_EDGE_LINES] + nonempty[-_EDGE_LINES:])
        kept = []
        for i, ln in enumerate(lines):
            if _PAGE_MARK.match(ln):
                continue
            if line_numbers and _DIGITS_ONLY.match(ln):
                continue
            if i in edge_idx and (_norm(ln) in repeated or _DIGITS_ONLY.match(ln)):
                continue
            kept.append(ln.rstrip())
        text = "\n".join(kept)
        text = re.sub(r"(?<=[a-z])-\n(?=[a-z])", "", text)   # 줄 끝 하이픈 단어 잇기
        text = _join_word_runs(text)
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        out.append(text.strip())
    return out
