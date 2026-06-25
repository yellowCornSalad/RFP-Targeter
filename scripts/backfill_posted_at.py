"""MSS·NIPA posted_at 백필 — 수정된 어댑터로 라이브 재파싱해 DB 교정.

버그(2026-06-25 발견):
  · MSS: 본문 fetch 실패 시 posted_at=today_iso 폴백 → 6/24 공고가 크롤일로 둔갑
  · NIPA: 행 첫 날짜(dates[0])가 제목 셀의 신청 시작일을 게시일로 오집음
둘 다 upsert 가 posted_at 을 무조건 덮어써서 DB 오염 누적.

이 스크립트는 수정된 어댑터를 라이브 실행해 정확한 posted_at 을 얻고,
DB 값과 다르면 교정한다.

사용: python scripts/backfill_posted_at.py [--apply]
"""
import sys

sys.path.insert(0, "src")

from rfp_targeter.config import settings
from rfp_targeter.crawlers import CRAWLERS
from rfp_targeter.db.models import get_conn

APPLY = "--apply" in sys.argv

for src in ["mss", "nipa"]:
    scfg = (settings().get("sources") or {}).get(src, {})
    crawler = CRAWLERS[src](base_url=scfg.get("base_url"))
    items = list(crawler.list_announcements())
    changes = []
    with get_conn() as conn:
        cur = conn.cursor()
        for a in items:
            # NIPA 는 fetch_detail 에서 상세 .infoDt 로 posted_at 보정 → 정확값 확보.
            # MSS 는 list 단계에서 이미 본문 등록일 파싱하므로 fetch_detail 불필요.
            if a.source == "nipa":
                try:
                    a = crawler.fetch_detail(a)
                except Exception:
                    pass
            if not a.posted_at:
                continue
            cur.execute("SELECT posted_at FROM announcement WHERE id=%s", (a.id,))
            row = cur.fetchone()
            if not row:
                continue
            old = row["posted_at"]
            if old != a.posted_at:
                changes.append((a.id, old, a.posted_at, (a.title or "")[:45]))
                if APPLY:
                    cur.execute(
                        "UPDATE announcement SET posted_at=%s WHERE id=%s",
                        (a.posted_at, a.id),
                    )
        if APPLY:
            conn.commit()
    print(f"=== {src.upper()}: 교정 {len(changes)}건 ({'APPLIED' if APPLY else 'DRY-RUN'}) ===")
    for cid, old, new, title in changes:
        print(f"  {cid}: {old} -> {new} | {title}")
    print()
