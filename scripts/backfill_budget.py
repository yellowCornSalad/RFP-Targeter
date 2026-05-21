"""기존 announcement의 body에서 예산을 다시 추출해 budget_mw 보강.

예산 정규식 강화 후(소수점·다양한 prefix 지원) 기존 데이터에 일괄 적용.

    python scripts/backfill_budget.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rfp_targeter.attachments.budget_extract import extract_budget_mw, extract_duration_months  # noqa: E402
from rfp_targeter.db.models import get_conn, init_db  # noqa: E402


def main():
    init_db()
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, body, budget_mw, duration_months
                FROM announcement
                WHERE body IS NOT NULL
                """
            )
            rows = cur.fetchall()
        print(f"대상: {len(rows):,}건 (body 있는 모든 공고)")

        new_budget = 0
        new_duration = 0
        updated_budget = 0
        with conn.cursor() as cur:
            for r in rows:
                new_mw = extract_budget_mw(r["body"])
                new_dm = extract_duration_months(r["body"])

                changes = []
                params = []
                if new_mw is not None and r["budget_mw"] != new_mw:
                    changes.append("budget_mw=%s")
                    params.append(new_mw)
                    if r["budget_mw"] is None:
                        new_budget += 1
                    else:
                        updated_budget += 1
                if new_dm is not None and r["duration_months"] != new_dm:
                    changes.append("duration_months=%s")
                    params.append(new_dm)
                    if r["duration_months"] is None:
                        new_duration += 1

                if changes:
                    params.append(r["id"])
                    cur.execute(
                        f"UPDATE announcement SET {', '.join(changes)} WHERE id=%s",
                        tuple(params),
                    )

    print()
    print("=== 백필 완료 ===")
    print(f"  신규 예산 채움 :  {new_budget:>4}건")
    print(f"  기존 예산 수정 :  {updated_budget:>4}건 (이전값 → 새 추출값)")
    print(f"  신규 기간 채움 :  {new_duration:>4}건")


if __name__ == "__main__":
    main()
