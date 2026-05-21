"""중복 공고 정리.

두 종류 중복 처리:

1. NIPA 내부 중복 — Python hash() 비결정적이라 같은 공고가 5~7건씩 쌓임
   → 같은 (title, posted_at) 그룹에서 최초 1건만 남기고 나머지 삭제
   → ID 우선순위: URL에 숫자 ID 있으면 그것, 없으면 가장 일찍 fetched_at

2. IITP/NTIS cross-source 중복 — 같은 nttSeqNo (external_id) 가 양쪽에서 수집
   → IITP 측 보존, NTIS 측 삭제 (IITP가 1차 소스, NTIS는 2차 보강)

실행:
    python scripts/cleanup_duplicates.py           # dry-run (확인만)
    python scripts/cleanup_duplicates.py --apply   # 실제 삭제
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rfp_targeter.db.models import get_conn  # noqa: E402


def cleanup_nipa_duplicates(apply: bool) -> int:
    """NIPA 중복 — 같은 title 그룹에서 1건 빼고 삭제."""
    print("\n=== 1. NIPA 내부 중복 ===")
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT title, COUNT(*) as cnt, array_agg(id) AS ids
                FROM announcement
                WHERE source = 'nipa'
                GROUP BY title
                HAVING COUNT(*) > 1
            """)
            groups = cur.fetchall()
        print(f"  중복 그룹: {len(groups)}건")

        total_to_delete: list[str] = []
        for g in groups:
            ids = g["ids"]
            # URL에 숫자 ID 있는 것 우선 보존 (가장 짧고 깔끔한 ID 선호)
            sorted_ids = sorted(ids, key=lambda x: (
                # external_id 부분에 's' 접두사(hash 폴백) 있으면 뒤로
                "h" in x.split(":")[-1],
                len(x),
            ))
            keep = sorted_ids[0]
            to_delete = sorted_ids[1:]
            total_to_delete.extend(to_delete)

        print(f"  삭제 대상: {len(total_to_delete):,}건")
        if apply and total_to_delete:
            with conn.cursor() as cur:
                # ON DELETE CASCADE → score / draft 도 함께 삭제됨
                cur.execute(
                    "DELETE FROM announcement WHERE id = ANY(%s)",
                    (total_to_delete,),
                )
            print(f"  ✅ 삭제 완료")
        elif total_to_delete:
            print(f"  (dry-run — 실제 삭제하려면 --apply)")
    return len(total_to_delete)


def cleanup_cross_source_duplicates(apply: bool) -> int:
    """IITP/NTIS 동일 nttSeqNo 중복 — NTIS 측 삭제 (IITP 우선)."""
    print("\n=== 2. IITP/NTIS cross-source 중복 ===")
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT i.external_id, i.title
                FROM announcement i
                JOIN announcement n ON n.external_id = i.external_id
                WHERE i.source = 'iitp' AND n.source = 'ntis'
            """)
            shared = cur.fetchall()
        print(f"  IITP/NTIS 공통 external_id: {len(shared)}건")

        if not shared:
            return 0

        # NTIS 쪽만 삭제 (IITP가 보존)
        ntis_ids = [f"ntis:{r['external_id']}" for r in shared]

        # 샘플 표시
        for s in shared[:3]:
            print(f"    - {s['external_id']}: {s['title'][:60]}")

        print(f"  삭제 대상 (NTIS): {len(ntis_ids):,}건")
        if apply:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM announcement WHERE id = ANY(%s)",
                    (ntis_ids,),
                )
            print(f"  ✅ 삭제 완료")
        else:
            print(f"  (dry-run — 실제 삭제하려면 --apply)")
    return len(ntis_ids)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="실제 삭제 (없으면 dry-run)")
    args = ap.parse_args()

    n_nipa = cleanup_nipa_duplicates(apply=args.apply)
    n_cross = cleanup_cross_source_duplicates(apply=args.apply)

    print(f"\n=== 합계 ===")
    print(f"  NIPA 중복:    {n_nipa:,}건")
    print(f"  cross 중복:   {n_cross:,}건")
    print(f"  총 삭제 대상: {n_nipa + n_cross:,}건")
    if not args.apply:
        print(f"\n  ※ dry-run — 실제 삭제하려면 다시 --apply 옵션과 함께 실행")


if __name__ == "__main__":
    main()
