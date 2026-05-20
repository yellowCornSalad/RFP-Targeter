"""크롤 1회 실행 (테스트용).

    python scripts/run_once.py
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rfp_targeter.pipeline import run_once  # noqa: E402

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    stats = run_once()
    print("\n=== 요약 ===")
    for s in stats:
        flag = f" ERROR: {s.error}" if s.error else ""
        print(f"  [{s.source}] 신규 {s.new} / 업데이트 {s.updated} / 보안통과 {s.filtered_in}{flag}")
