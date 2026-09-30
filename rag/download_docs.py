"""공식 출처에서 RAG 문서를 받아 data/raw/ 에 저장한다. 이미 있는 파일은 건너뛴다.

실행: python -m rag.download_docs
"""
import urllib.request
from pathlib import Path

from rag.sources import DOCS

RAW_DIR = Path(__file__).resolve().parents[1] / "data" / "raw"
HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                         "(KHTML, like Gecko) Chrome/128.0 Safari/537.36"}


def main() -> list[str]:
    """받지 못한 문서 이름 목록을 돌려준다. 하나가 실패해도 멈추지 않고 나머지를 받는다."""
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    missing = []
    for name, info in DOCS.items():
        path = RAW_DIR / name
        if path.exists():
            print(f"있음   {name}")
            continue
        if "url" not in info:
            note = "선택 문서, 없어도 됨" if info.get("optional") else "직접 받아 data/raw/에 넣기"
            print(f"건너뜀 {name} ({note}: {info['source_url']})")
            missing.append(name)
            continue
        try:
            req = urllib.request.Request(info["url"], headers=HEADERS)
            data = urllib.request.urlopen(req, timeout=60).read()
            if not data.startswith(b"%PDF"):
                raise ValueError("PDF가 아닌 응답")
            path.write_bytes(data)
            print(f"받음   {name} ({len(data) // 1024:,} KB)")
        except Exception as e:   # 출처 사이트가 막혀도 나머지 문서로 계속 진행한다
            print(f"실패   {name} ({e}) → 브라우저로 {info['url']} 을 받아 data/raw/{name} 으로 저장")
            missing.append(name)
    if missing:
        print(f"\n없는 문서 {len(missing)}개 — 나머지 문서로 진행한다: {', '.join(missing)}")
    return missing


if __name__ == "__main__":
    main()
