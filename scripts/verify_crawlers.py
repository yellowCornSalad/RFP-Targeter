"""각 크롤러 어댑터 검증 — 소스별 3건씩 받아서 핵심 필드 출력.

사용:
    python scripts/verify_crawlers.py

목적:
  - 각 어댑터가 실제로 데이터를 가져오는지 (HTTP 응답·파싱 모두)
  - external_id·title·url·posted_at 가 합리적으로 채워지는지
  - 실패 시 어느 단계에서 깨지는지 (네트워크/파싱/필드매핑)
"""
from __future__ import annotations

import logging
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

# 로그는 WARNING 이상만 (검증 보고에 집중)
logging.basicConfig(level=logging.WARNING, format="  ! %(name)s: %(message)s")

from rfp_targeter.config import settings  # noqa: E402
from rfp_targeter.crawlers import CRAWLERS  # noqa: E402

SAMPLE_N = 3


def verify_one(name: str, cls):
    cfg = (settings().get("sources") or {}).get(name, {})
    enabled = cfg.get("enabled", False)
    status = "ON" if enabled else "off"
    print(f"\n=== [{name}] {status} ({cls.__name__}) " + "=" * 30)
    if not enabled:
        print("  (skip — settings.yaml에서 enabled=false)")
        return
    base_url = cfg.get("base_url")
    try:
        c = cls(base_url=base_url)
    except Exception as e:
        print(f"  ❌ 인스턴스화 실패: {e}")
        return

    # 검증용으로 max_per_source 작게
    c.max_per_source = SAMPLE_N

    t0 = time.time()
    rows = []
    try:
        for a in c.list_announcements():
            rows.append(a)
            if len(rows) >= SAMPLE_N:
                break
    except Exception as e:
        print(f"  ❌ list_announcements 실패: {type(e).__name__}: {e}")
        traceback.print_exc(limit=2)
        return
    dt = time.time() - t0

    if not rows:
        print(f"  ⚠️  0건 (시간 {dt:.1f}초) — 네트워크/엔드포인트/필터 확인 필요")
        return

    print(f"  ✅ {len(rows)}건 수집 ({dt:.1f}초)")
    for i, a in enumerate(rows, 1):
        title = (a.title or "")[:60]
        agency = (a.agency or "?")[:25]
        url_short = (a.url or "")[:50]
        posted = a.posted_at or "?"
        ext = a.external_id or "?"
        print(f"   {i}. [{posted}] [{agency}]")
        print(f"      {title}")
        print(f"      id={ext}  url={url_short}")


def main():
    print(f"검증 시작 — 각 소스 최대 {SAMPLE_N}건씩\n")
    # 정렬: 등록된 순서대로 (CRAWLERS 사전 순)
    for name in sorted(CRAWLERS.keys()):
        if name == "mock":  # 검증 대상 제외
            continue
        cls = CRAWLERS[name]
        try:
            verify_one(name, cls)
        except Exception as e:
            print(f"  ❌ 예상치 못한 오류: {e}")
            traceback.print_exc(limit=2)
    print("\n=== 검증 종료 ===")


if __name__ == "__main__":
    main()
