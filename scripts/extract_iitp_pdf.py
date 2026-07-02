"""IITP 시뮬레이터 제안서 PDF 56쪽 전체 추출 → 섹션별 raw 텍스트 저장.

산출: data/raw/iitp-simulator-text.json
  {pages: [{"num": 1, "text": "..."}, ...]}

이걸 docs/proposals/iitp-simulator-2026.md 작성에 사용.
"""
import json
from pathlib import Path

import pdfplumber

SRC = Path(r"D:\RFP-Targeter\data\raw\iitp-simulator-2026.pdf")
OUT = Path(r"D:\RFP-Targeter\data\raw\iitp-simulator-text.json")

pages = []
with pdfplumber.open(SRC) as pdf:
    for i, p in enumerate(pdf.pages):
        text = (p.extract_text() or "").strip()
        pages.append({"num": i + 1, "text": text, "chars": len(text)})

OUT.write_text(
    json.dumps({"pages": pages}, ensure_ascii=False, indent=2),
    encoding="utf-8",
)

# 요약 통계
total_chars = sum(p["chars"] for p in pages)
print(f"총 {len(pages)}쪽, {total_chars:,} chars")
print(f"평균 {total_chars // len(pages):,} chars/page")
print(f"저장 → {OUT}")
print()
print("쪽별 글자수 (목차 파악용):")
for p in pages:
    bar = "#" * (p["chars"] // 100)
    print(f"  p{p['num']:2d}  {p['chars']:5d}  {bar}")
