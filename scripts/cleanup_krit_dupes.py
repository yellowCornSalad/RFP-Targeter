"""KRIT 중복/묵은 행 정리 (1회성).

배경: external_id 가 builtin hash() 기반이라 매 크롤마다 id 가 바뀌어
      같은 공고가 중복 INSERT 됨. + 군용 제외 이전 묵은 행(무인기 터빈 등)도 잔존.
조치: 현재 노출 중(is_dismissed=FALSE)인 KRIT 행을 전부 soft-delete.
      이후 hashlib(결정적) 수정된 크롤러가 깨끗한 5건을 새 결정적 id 로 재삽입.
      (hard delete 아님 — is_dismissed=TRUE 로 숨김. 되돌릴 수 있음.)

실행: python scripts/cleanup_krit_dupes.py            # dry-run (보기만)
      python scripts/cleanup_krit_dupes.py --apply    # 실제 soft-delete
"""
from __future__ import annotations

import sys

from rfp_targeter.db.models import get_conn


def main() -> int:
    apply = "--apply" in sys.argv
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, deadline_at, is_dismissed, title "
                "FROM announcement WHERE source='krit' ORDER BY is_dismissed, deadline_at"
            )
            rows = cur.fetchall()
            visible = [r for r in rows if not r["is_dismissed"]]
            print(f"=== KRIT 전체 {len(rows)}행 (노출 {len(visible)} / 숨김 {len(rows)-len(visible)}) ===")
            for r in rows:
                flag = "숨김" if r["is_dismissed"] else "노출"
                print(f"  [{flag}] {r['id']}  [{r['deadline_at']}] {r['title'][:45]}")

            if not apply:
                print(f"\n[dry-run] 노출 {len(visible)}건을 soft-delete 예정. 실제 적용: --apply")
                return 0

            cur.execute(
                "UPDATE announcement SET is_dismissed=TRUE "
                "WHERE source='krit' AND is_dismissed=FALSE"
            )
            print(f"\n[적용] {cur.rowcount}건 soft-delete (is_dismissed=TRUE)")

            cur.execute(
                "SELECT COUNT(*) AS n FROM announcement "
                "WHERE source='krit' AND is_dismissed=FALSE"
            )
            print(f"남은 노출 KRIT: {cur.fetchone()['n']}건 (0이어야 정상)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
