"""score 테이블이 비어 있는 보안 통과 공고에 5축 점수 일괄 계산.

원인: 키워드 카테고리 200개 대폭 추가(#88) 후 기존 DB 행들이 is_security=True 로
재마킹됐지만 점수 재계산이 안 됐음. 또 일부 신규 cron 사이클에서도 transaction 또는
순서 문제로 score INSERT가 누락된 케이스 존재.

사용:
    python scripts/backfill_scores.py            # 활성 공고만(권장)
    python scripts/backfill_scores.py --all      # is_security=TRUE 전체

활성 = 마감일 미래 OR (마감미명시 AND 등록 60일 내).
"""
from __future__ import annotations

import argparse
import json
import logging
import sys

from rfp_targeter.db.models import Announcement, get_conn, upsert_score
from rfp_targeter.scoring import compute_score

log = logging.getLogger("backfill_scores")


_ANN_ALLOWED = {
    "source", "external_id", "title", "url", "agency",
    "posted_at", "deadline_at", "budget_mw", "duration_months",
    "budget_period", "budget_excerpt", "budget_confidence",
    "summary", "body", "is_security",
    "eligibility_status", "eligibility_note", "eligibility_limit",
    "application_start_date",
}


def _row_to_announcement(r: dict) -> Announcement:
    """DB row(dict)를 Announcement 데이터클래스로 변환.

    JSON 컬럼(attachments_json, matched_keywords_json)은 list로 디코드해서
    각각 attachments / matched_keywords 필드로 매핑.
    """
    d = {k: v for k, v in r.items() if k in _ANN_ALLOWED}
    try:
        d["attachments"] = json.loads(r.get("attachments_json") or "[]")
    except Exception:
        d["attachments"] = []
    try:
        d["matched_keywords"] = json.loads(r.get("matched_keywords_json") or "[]")
    except Exception:
        d["matched_keywords"] = []
    return Announcement(**d)


def backfill(active_only: bool = True) -> tuple[int, int]:
    """score 누락 행 일괄 백필. Returns (성공, 실패)."""
    where_extra = ""
    if active_only:
        where_extra = (
            " AND (a.deadline_at >= CURRENT_DATE::text "
            " OR (a.deadline_at IS NULL AND a.posted_at >= (CURRENT_DATE - 60)::text))"
        )

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT a.*
                FROM announcement a
                LEFT JOIN score s ON s.announcement_id = a.id
                WHERE s.announcement_id IS NULL
                  AND a.is_security = TRUE
                  AND a.is_dismissed = FALSE
                  {where_extra}
                ORDER BY a.posted_at DESC NULLS LAST
                """
            )
            rows = cur.fetchall()

    log.info("score 누락 %d건 — 백필 시작", len(rows))
    ok, fail = 0, 0
    for r in rows:
        try:
            a = _row_to_announcement(r)
            sc = compute_score(a)
            with get_conn() as conn:
                upsert_score(conn, sc)
            ok += 1
            if ok % 50 == 0:
                log.info("  진행 %d/%d", ok, len(rows))
        except Exception as e:
            fail += 1
            log.warning("FAIL %s: %s", r.get("id"), e)
    log.info("백필 완료: 성공 %d / 실패 %d", ok, fail)
    return ok, fail


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true", help="활성 필터 무시, 보안=TRUE 전체")
    args = ap.parse_args()
    ok, fail = backfill(active_only=not args.all)
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
