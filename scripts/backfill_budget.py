"""기존 announcement의 body에서 예산·기간·원문발췌 재추출 보강.

새 추출기는 hallucination 방지 위해:
- 본문에 명시된 값만 사용 (raw_excerpt 첨부)
- period_label (단년/연간/총사업비/N차년도 등) 함께 저장
- confidence (high/medium) 표시

기존 옛 추출기로 채운 budget_mw 중 excerpt 없는 건 신뢰도 낮음 → 추출 재시도 후
못 찾으면 NULL로 클리어 (가짜 값 안 보여주기).

    python scripts/backfill_budget.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rfp_targeter.attachments.budget_extract import extract_budget_info  # noqa: E402
from rfp_targeter.db.models import get_conn, init_db  # noqa: E402


def main():
    init_db()  # 새 컬럼 추가
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, body, budget_mw, duration_months,
                       budget_period, budget_excerpt, budget_confidence
                FROM announcement
                WHERE body IS NOT NULL
                """
            )
            rows = cur.fetchall()
        print(f"대상: {len(rows):,}건 (body 있는 모든 공고)")

        new_budget = 0
        updated_budget = 0
        cleared = 0
        new_duration = 0
        new_period = 0

        with conn.cursor() as cur:
            for r in rows:
                info = extract_budget_info(r["body"])

                if info:
                    # 새 추출 결과로 5개 필드 모두 갱신 (일관성)
                    if r["budget_mw"] is None:
                        new_budget += 1
                    elif r["budget_mw"] != info.mw:
                        updated_budget += 1
                    if r["budget_period"] != info.period_label:
                        new_period += 1
                    if info.duration_months and r["duration_months"] != info.duration_months:
                        new_duration += 1

                    dm_new = info.duration_months if info.duration_months else r["duration_months"]
                    cur.execute(
                        """UPDATE announcement SET
                            budget_mw=%s, duration_months=%s,
                            budget_period=%s, budget_excerpt=%s, budget_confidence=%s
                           WHERE id=%s""",
                        (info.mw, dm_new, info.period_label,
                         info.raw_excerpt, info.confidence, r["id"]),
                    )
                else:
                    # 추출 실패. 기존에 옛 추출기로 budget_mw만 있고 excerpt 없으면 클리어
                    # (가짜 값 노출 방지)
                    if r["budget_mw"] is not None and r["budget_excerpt"] is None:
                        cur.execute(
                            """UPDATE announcement SET
                                budget_mw=NULL, budget_period=NULL,
                                budget_excerpt=NULL, budget_confidence=NULL
                               WHERE id=%s""",
                            (r["id"],),
                        )
                        cleared += 1

    print()
    print("=== 백필 완료 ===")
    print(f"  신규 예산 채움    :  {new_budget:>4}건")
    print(f"  기존 예산 수정    :  {updated_budget:>4}건 (옛값 → 새 추출값)")
    print(f"  신뢰 안되는 값 클리어: {cleared:>4}건 (excerpt 없는 옛 추출 → NULL)")
    print(f"  신규 기간(개월) 채움: {new_duration:>4}건")
    print(f"  신규 period 라벨   :  {new_period:>4}건")


if __name__ == "__main__":
    main()
