"""IRIS 어댑터 smoke test — 목록 5건 받아 출력 (DB 안 건드림).

검증:
  · POST JSON API 정상 호출
  · _parse_item 으로 Announcement 변환
  · 마감일·시작일·부처 모두 들어왔는지
"""
from __future__ import annotations
import sys, logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rfp_targeter.crawlers.iris import IRISCrawler

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


def main():
    c = IRISCrawler(base_url="https://www.iris.go.kr")
    c.max_per_source = 5   # 5건만

    print("=" * 75)
    print("IRIS 어댑터 smoke test (5건)")
    print("=" * 75)

    count = 0
    for a in c.list_announcements():
        count += 1
        print(f"\n[{count}] {a.title[:70]}")
        print(f"     ext_id:    {a.external_id}")
        print(f"     agency:    {a.agency}")
        print(f"     posted:    {a.posted_at}")
        print(f"     deadline:  {a.deadline_at}")
        print(f"     app_start: {a.application_start_date}")
        print(f"     summary:   {a.summary}")
        print(f"     url:       {a.url[:80]}")

    print(f"\n총 {count}건 수집 — { 'OK' if count == 5 else '예상과 다름' }")


if __name__ == "__main__":
    main()
