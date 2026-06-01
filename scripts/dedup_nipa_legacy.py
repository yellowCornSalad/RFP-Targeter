"""NIPA 묵은 hash-ID 중복 row 정리 (1회성).

옛 크롤러가 URL ID 추출 실패 시 abs(hash(title)) 를 external_id 로 써서
같은 공고가 매 크롤마다 새 row 로 쌓인 잔재를 청소한다.

판정: 같은 (title, source) 그룹에 'URL 경로번호 == external_id 끝번호' 인
'정식' row 가 존재하면, 같은 그룹의 '불일치' row 를 soft dismiss.
→ 정식 row 가 없는 그룹(iitp/mss 등 실제 별개 게시물)은 건드리지 않음.

    python scripts/dedup_nipa_legacy.py            # dry-run (기본)
    python scripts/dedup_nipa_legacy.py --apply     # 실제 is_dismissed=TRUE
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from rfp_targeter.db.models import get_conn  # noqa: E402


def url_num(url: str) -> str | None:
    m = re.search(r"/(\d+)(?:\?|$|/)", url or "")
    return m.group(1) if m else None


def ext_num(eid: str) -> str | None:
    m = re.search(r"-(\d+)$", eid or "")
    return m.group(1) if m else None


def find_stale() -> list[dict]:
    with get_conn() as c:
        with c.cursor() as cur:
            cur.execute(
                """SELECT id, title, source, external_id, url, alerted_at
                   FROM announcement
                   WHERE is_dismissed = FALSE AND is_security = TRUE
                     AND source IN ('iitp','kisa','krit','nipa','mss','koica')
                     AND (deadline_at >= CURRENT_DATE::text
                          OR (deadline_at IS NULL AND posted_at >= (CURRENT_DATE - 60)::text))
                     AND (title, source) IN (
                       SELECT title, source FROM announcement
                       WHERE is_dismissed = FALSE AND is_security = TRUE
                         AND source IN ('iitp','kisa','krit','nipa','mss','koica')
                         AND (deadline_at >= CURRENT_DATE::text
                              OR (deadline_at IS NULL AND posted_at >= (CURRENT_DATE - 60)::text))
                       GROUP BY title, source HAVING COUNT(*) > 1)"""
            )
            rows = cur.fetchall()

    groups: dict = {}
    for r in rows:
        groups.setdefault((r["source"], r["title"]), []).append(r)

    stale = []
    for grp in groups.values():
        classed = [(r, (url_num(r["url"]) == ext_num(r["external_id"])
                        and url_num(r["url"]) is not None)) for r in grp]
        has_canonical = any(m for _, m in classed)
        if not has_canonical:
            continue  # 정식 row 없는 그룹 = 실제 별개 게시물, 보존
        for r, match in classed:
            if not match:
                stale.append(r)
    return stale


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="실제 is_dismissed=TRUE")
    args = ap.parse_args()

    stale = find_stale()
    print(f"=== NIPA 묵은 hash-ID 정리 대상: {len(stale)}건 ===")
    for r in stale:
        al = "Y" if r["alerted_at"] else "-"
        print(f"  {r['source']:5s} {r['external_id']:22s} alerted={al}  {r['title'][:40]}")

    if not stale:
        print("정리할 row 없음.")
        return 0

    if not args.apply:
        print("\n[dry-run] --apply 를 붙이면 실제 soft dismiss 합니다.")
        return 0

    ids = [r["id"] for r in stale]
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE announcement SET is_dismissed = TRUE WHERE id = ANY(%s)",
                (ids,),
            )
    print(f"\n✅ {len(ids)}건 soft dismiss 완료 (is_dismissed=TRUE).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
