"""IRIS 화이트리스트 미통과 공고를 is_dismissed=TRUE 처리.

광범위 키워드(사업공고/공모/연구개발)로 통과해 들어온 보안 비관련 IRIS 공고들을
사이트에서 제거. DB row 는 보존 (회고용).
"""
import sys
sys.path.insert(0, "src")

from rfp_targeter.db.models import get_conn
from rfp_targeter.crawlers.iris import _matches_whitelist


def main(dry_run: bool = False):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, title, summary, agency
              FROM announcement
             WHERE source = 'iris'
               AND is_dismissed = FALSE
        """)
        rows = cur.fetchall()

        keep, dismiss = [], []
        for row in rows:
            ann_id = row["id"]
            title = row["title"] or ""
            summary = row["summary"] or ""
            agency = row["agency"] or ""
            if _matches_whitelist(title, summary, agency):
                keep.append((ann_id, title))
            else:
                dismiss.append((ann_id, title))

        print(f"활성 IRIS 공고: {len(rows)}건")
        print(f"  · 화이트리스트 통과(유지): {len(keep)}건")
        print(f"  · 화이트리스트 미통과(soft delete): {len(dismiss)}건")

        print("\n--- 유지 (상위 6) ---")
        for _id, t in keep[:6]:
            print(f"  + {t[:70]}")

        print("\n--- 제거 예정 (상위 8) ---")
        for _id, t in dismiss[:8]:
            print(f"  - {t[:70]}")

        if dry_run:
            print("\n[DRY RUN] DB 변경 없음. --apply 로 실제 처리.")
            return

        if not dismiss:
            print("\n제거할 항목 없음.")
            return

        ids = [d[0] for d in dismiss]
        cur.execute(
            "UPDATE announcement SET is_dismissed = TRUE WHERE id = ANY(%s)",
            (ids,),
        )
        conn.commit()
        print(f"\n✅ {len(dismiss)}건 is_dismissed=TRUE 처리 완료.")


if __name__ == "__main__":
    main(dry_run="--apply" not in sys.argv)
