"""enkiwhitehat.com 에서 회사 프로필 자동 추출 → config/profile.yaml 초안 생성.

    python scripts/init_profile.py
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rfp_targeter.profile.extractor import extract_profile, save_profile_yaml  # noqa: E402

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    print("[..] enkiwhitehat.com 크롤링 시작...")
    p = extract_profile()
    dest = save_profile_yaml(p)
    print(f"\n[OK] 초안 저장: {dest}")
    print("\n다음 단계:")
    print("  1. config/profile.yaml 열기")
    print("  2. ??? 표시된 항목 채우기 (especially: technologies, track_record, competitors)")
    print("  3. _extracted 섹션 확인해서 빠진 키워드 보강")
