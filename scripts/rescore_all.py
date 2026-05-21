"""기존 모든 announcement의 score 재계산 (점수식 튜닝 후 백필).

점수 산정 룰이 바뀌면 다음 크롤 사이클까지 기다리지 않고 즉시 적용.

    python scripts/rescore_all.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rfp_targeter.db.models import Announcement, get_conn, init_db, upsert_score  # noqa: E402
from rfp_targeter.scoring.engine import compute_score  # noqa: E402


def main():
    init_db()
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM announcement WHERE is_security = TRUE")
            rows = cur.fetchall()
        print(f"보안 통과 공고: {len(rows):,}건 재산정 시작...")

        bucket = {b: 0 for b in [0, 10, 20, 30, 40, 50, 60, 70, 80, 90]}
        for r in rows:
            try:
                mks = json.loads(r["matched_keywords_json"] or "[]")
            except Exception:
                mks = []
            try:
                atts = json.loads(r["attachments_json"] or "[]")
            except Exception:
                atts = []
            a = Announcement(
                source=r["source"], external_id=r["external_id"],
                title=r["title"] or "", url=r["url"] or "",
                agency=r["agency"],
                posted_at=r["posted_at"],
                deadline_at=r["deadline_at"],
                budget_mw=r["budget_mw"],
                duration_months=r["duration_months"],
                summary=r["summary"], body=r["body"],
                attachments=atts,
                matched_keywords=mks,
                is_security=True,
            )
            s = compute_score(a)
            upsert_score(conn, s)
            b = min(int(s.total_score) // 10 * 10, 90)
            bucket[b] = bucket.get(b, 0) + 1

    print()
    print("=== 재산정 후 분포 ===")
    for b in sorted(bucket.keys()):
        n = bucket[b]
        bar = "█" * min(n // 5, 60)
        print(f"  {b:>3}~{b+9:>3}: {n:>4} {bar}")
    print()
    print("이제 대시보드 새로고침하면 새 점수 분포 반영됨.")


if __name__ == "__main__":
    main()
