"""사용자 명시 7개 source 누락 자동 검증.

사용자 요구 (2026-05 확정):
  KISA · KOSA · IITP · KRIT · KOICA · NIPA · 중기부(MSS)

매 코드 변경/배포 전후 호출 권장. 누락 source 있으면 비-0 exit code.

실행:
    python scripts/verify_sources.py           # 검증만
    python scripts/verify_sources.py --strict  # 누락 1개라도 있으면 exit 1
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rfp_targeter.config import settings  # noqa: E402
from rfp_targeter.db.models import get_conn  # noqa: E402


# 사용자 명시 (불변)
REQUIRED_SOURCES = {
    "kisa":  "KISA",
    "kosa":  "KOSA",
    "iitp":  "IITP",
    "krit":  "KRIT",
    "koica": "KOICA",
    "nipa":  "NIPA",
    "mss":   "중기부 (MSS)",
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--strict", action="store_true",
                    help="누락 1개라도 있으면 exit 1")
    args = ap.parse_args()

    # 1. settings.yaml 활성화 상태
    src_cfg = settings().get("sources") or {}
    enabled_set = {s for s, c in src_cfg.items() if c.get("enabled")}

    # 2. DB 카운트
    counts: dict[str, int] = {}
    last_fetched: dict[str, str | None] = {}
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT source, COUNT(*) AS c, MAX(fetched_at) AS lf "
                "FROM announcement GROUP BY source"
            )
            for r in cur.fetchall():
                counts[r["source"]] = r["c"]
                last_fetched[r["source"]] = r["lf"]

    # 3. 검증
    print("=" * 70)
    print("필수 source 검증 (사용자 명시 7개)")
    print("=" * 70)
    print(f"{'source':10s} {'표시명':18s} {'enabled':9s} {'DB건수':>7s} {'마지막 fetch':25s} {'상태'}")
    print("-" * 90)

    missing: list[str] = []
    inactive: list[str] = []

    for src_key, src_name in REQUIRED_SOURCES.items():
        is_enabled = src_key in enabled_set
        cnt = counts.get(src_key, 0)
        lf = last_fetched.get(src_key, "—")
        if not is_enabled:
            status = "❌ 비활성화"
            inactive.append(src_key)
        elif cnt == 0:
            status = "⚠ 데이터 0건"
            missing.append(src_key)
        elif cnt < 5:
            status = "⚠ 데이터 부족"
        else:
            status = "✓ OK"
        print(f"{src_key:10s} {src_name:18s} "
              f"{'✓' if is_enabled else '✗':9s} {cnt:>7d} "
              f"{(lf or '—')[:19]:25s} {status}")

    # 비활성/누락 외 source (사용자 목록에 없는데 DB에 있는 것 = 정리 후보)
    extra_sources = set(counts.keys()) - set(REQUIRED_SOURCES.keys())
    if extra_sources:
        print()
        print(f"⚠ 사용자 목록 외 source (정리 검토): {sorted(extra_sources)}")
        for s in sorted(extra_sources):
            print(f"  {s}: {counts.get(s, 0)}건")

    # 결과
    print()
    if not inactive and not missing:
        print("✅ 모든 필수 source가 활성화 + 데이터 있음")
        sys.exit(0)
    else:
        print(f"❌ 문제 발견:")
        if inactive:
            print(f"  비활성화: {inactive}")
        if missing:
            print(f"  데이터 0건: {missing}")
        if args.strict:
            sys.exit(1)


if __name__ == "__main__":
    main()
