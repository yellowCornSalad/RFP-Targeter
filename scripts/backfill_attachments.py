"""첨부 없는 기존 공고들 재크롤링 → 첨부 파싱 보강.

대상: source IN ('kisa', 'nipa', 'mss') 중 attachments_json 비어있는 것.

각 어댑터의 fetch_detail() 재실행 → URL에서 첨부 링크 파싱 → DB 업데이트.

    python scripts/backfill_attachments.py
    python scripts/backfill_attachments.py --source kisa  # 단일 소스만
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rfp_targeter.crawlers.kisa import KISACrawler  # noqa: E402
from rfp_targeter.crawlers.mss import MSSCrawler  # noqa: E402
from rfp_targeter.crawlers.nipa import NIPACrawler  # noqa: E402
from rfp_targeter.db.models import Announcement, get_conn, init_db  # noqa: E402


CRAWLERS = {
    "kisa": KISACrawler,
    "nipa": NIPACrawler,
    "mss": MSSCrawler,
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=list(CRAWLERS.keys()), default=None,
                    help="단일 소스만 백필 (기본: 전체)")
    ap.add_argument("--limit", type=int, default=None,
                    help="최대 N건만 처리 (테스트용)")
    args = ap.parse_args()

    targets = [args.source] if args.source else list(CRAWLERS.keys())

    init_db()

    # 소스별 크롤러 인스턴스 — base_url은 settings에서 자동 로드, fetch_detail만 호출
    instances: dict[str, object] = {}
    for src in targets:
        cls = CRAWLERS[src]
        instances[src] = cls()

    total_processed = 0
    total_added = 0
    total_failed = 0

    for src in targets:
        crawler = instances[src]
        # 대상 row 가져오기
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT id, source, external_id, title, url, agency,
                              posted_at, deadline_at, body, attachments_json
                       FROM announcement
                       WHERE source = %s
                       AND (attachments_json IS NULL OR attachments_json IN ('', '[]'))
                       ORDER BY posted_at DESC NULLS LAST""",
                    (src,),
                )
                rows = cur.fetchall()

        if args.limit:
            rows = rows[:args.limit]

        print(f"\n=== {src.upper()} : 대상 {len(rows):,}건 ===")

        for i, r in enumerate(rows, 1):
            # Announcement 객체 재구성 (fetch_detail 입력용)
            a = Announcement(
                source=r["source"],
                external_id=r["external_id"],
                title=r["title"],
                url=r["url"],
                agency=r["agency"],
                posted_at=r["posted_at"],
                deadline_at=r["deadline_at"],
                body=r["body"] or "",
            )
            try:
                a = crawler.fetch_detail(a)
            except Exception as e:
                total_failed += 1
                if i % 10 == 0 or i == len(rows):
                    print(f"  [{i:4d}/{len(rows)}] fetch_detail fail: {e}")
                continue

            if a.attachments:
                # DB 업데이트
                with get_conn() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            "UPDATE announcement SET attachments_json=%s, updated_at=NOW() WHERE id=%s",
                            (json.dumps(a.attachments, ensure_ascii=False), r["id"]),
                        )
                total_added += 1

            total_processed += 1
            if i % 10 == 0 or i == len(rows):
                print(f"  [{i:4d}/{len(rows)}] 처리 완료 ({total_added}건 첨부 추가)")
            time.sleep(0.3)  # rate limit

    print()
    print("=== 백필 완료 ===")
    print(f"  처리:        {total_processed}건")
    print(f"  첨부 추가:    {total_added}건")
    print(f"  실패:        {total_failed}건")


if __name__ == "__main__":
    main()
