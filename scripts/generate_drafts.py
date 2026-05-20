"""점수 임계점 이상 공고에 대해 일괄 초안 생성.

    python scripts/generate_drafts.py [min_score]
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rfp_targeter.config import settings  # noqa: E402
from rfp_targeter.drafter.draft_generator import generate_for_high_scoring  # noqa: E402

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    min_score = float(sys.argv[1]) if len(sys.argv) > 1 else settings()["auto_draft"]["min_total_score"]
    paths = generate_for_high_scoring(min_score)
    print(f"[OK] {len(paths)}개 초안 생성 (>= {min_score}점)")
    for p in paths:
        print(f"  - {p}")
