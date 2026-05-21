"""기존 DB의 announcement 전체에 자격 검증 결과 백필.

신규 컬럼 eligibility_status / eligibility_note / eligibility_limit 가 NULL인
기존 행에 대해 본문 다시 분석해서 채움. 일회성 실행.

    python scripts/backfill_eligibility.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rfp_targeter.config import profile  # noqa: E402
from rfp_targeter.db.models import get_conn, init_db  # noqa: E402
from rfp_targeter.filters.eligibility import check_eligibility  # noqa: E402


def main():
    init_db()  # 마이그레이션 보장

    company = (profile() or {}).get("company") or {}
    est = company.get("established_year")
    if not isinstance(est, int):
        print(f"established_year 미설정 또는 비정수 ({est!r}). 백필 skip.")
        return
    print(f"회사 설립연도: {est}, 백필 시작...")

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, title, body FROM announcement")
            rows = cur.fetchall()
        print(f"대상: {len(rows):,}건")

        updated = {"ok": 0, "blocked": 0, "unsure": 0, "unknown": 0}
        with conn.cursor() as cur:
            for r in rows:
                er = check_eligibility(
                    body=r["body"], title=r["title"],
                    established_year=est,
                )
                cur.execute(
                    """
                    UPDATE announcement SET
                        eligibility_status = %s,
                        eligibility_note = %s,
                        eligibility_limit = %s
                    WHERE id = %s
                    """,
                    (er.status, er.note, er.limit_years, r["id"]),
                )
                updated[er.status] = updated.get(er.status, 0) + 1

    print(f"\n=== 백필 완료 ===")
    print(f"  ok      : {updated['ok']:,} (자격 적합 또는 자격 조건 없음)")
    print(f"  blocked : {updated['blocked']:,} (창업 N년차 미달 의심)")
    print(f"  unsure  : {updated['unsure']:,} (대표자 기준 등 별도 확인)")
    print(f"  unknown : {updated['unknown']:,} (설립연도 미설정)")


if __name__ == "__main__":
    main()
