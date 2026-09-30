"""공식 출처에서 RAG 문서를 받아 data/raw/ 에 저장한다. 이미 있는 파일은 건너뛴다.

실행: python -m rag.download_docs
"""
import urllib.request
from pathlib import Path

from rag.sources import DOCS

RAW_DIR = Path(__file__).resolve().parents[1] / "data" / "raw"
HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                         "(KHTML, like Gecko) Chrome/128.0 Safari/537.36"}


def main():
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    for name, info in DOCS.items():
        path = RAW_DIR / name
        if path.exists():
            print(f"있음   {name}")
            continue
        if "url" not in info:
            note = "선택 문서, 없어도 됨" if info.get("optional") else "직접 받아 data/raw/에 넣기"
            print(f"건너뜀 {name} ({note}: {info['source_url']})")
            continue
        req = urllib.request.Request(info["url"], headers=HEADERS)
        data = urllib.request.urlopen(req, timeout=60).read()
        if not data.startswith(b"%PDF"):
            raise RuntimeError(f"{name}: PDF가 아닌 응답 — {info['url']} 을 브라우저로 받아 넣기")
        path.write_bytes(data)
        print(f"받음   {name} ({len(data) // 1024:,} KB)")


if __name__ == "__main__":
    main()
