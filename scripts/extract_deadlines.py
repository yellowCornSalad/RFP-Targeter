"""마감일 NULL 공고의 본문에서 신청 마감일을 LLM 으로 추출해 deadline_at 채움.

배경 (2026-06-02): IITP 등 data.go.kr API 공고는 마감일이 NULL → '등록 60일내' 추정으로만
활성 판단했음. 본문에서 '신청 제출 마감'을 LLM 으로 뽑아 deadline_at 에 저장하면,
활성 필터(마감 미래)와 dismiss_expired(마감<오늘)가 '확신'으로 동작.

대상: is_security, 미dismiss, deadline_at IS NULL/'' , 본문 300자+ (추출할 내용 있는 것).
안전: 이미 deadline_at 있으면 건드리지 않음 (API 제공 마감 보존).

    python scripts/extract_deadlines.py --dry-run --limit 10   # 저장 없이 출력만 (정확도 확인)
    python scripts/extract_deadlines.py --limit 50             # 50건 처리
    python scripts/extract_deadlines.py                        # 전체 (NULL 마감 전부)
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rfp_targeter.db.models import get_conn  # noqa: E402
from rfp_targeter.deadline_extract import extract_deadline  # noqa: E402

log = logging.getLogger("extract_deadlines")


def run(limit: int | None, dry: bool, force: bool = False) -> int:
    limit_clause = f"LIMIT {int(limit)}" if limit else ""
    # force 아니면 '아직 검사 안 한' 것만 (마감없음 판정된 건 deadline_checked_at 차서 재처리 안 됨)
    checked_clause = "" if force else "AND deadline_checked_at IS NULL"
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""SELECT id, title, posted_at, body
                    FROM announcement
                    WHERE is_security = TRUE AND is_dismissed = FALSE
                      AND source IN ('iitp','kisa','krit','nipa','mss','koica')
                      AND (deadline_at IS NULL OR deadline_at = '')
                      {checked_clause}
                      AND LENGTH(COALESCE(body,'')) >= 300
                    ORDER BY posted_at DESC NULLS LAST
                    {limit_clause}"""
            )
            rows = cur.fetchall()

    log.info("마감일 추출 대상: %d건 (dry=%s, force=%s)", len(rows), dry, force)
    now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
    found, none_cnt = 0, 0
    for r in rows:
        dl = extract_deadline(r["title"], r["body"], posted_at=r["posted_at"])
        if dl is None:
            time.sleep(1.0)  # 일시 오류 대비 1회 재시도
            dl = extract_deadline(r["title"], r["body"], posted_at=r["posted_at"])
        if dl is None:
            none_cnt += 1
            log.info("  [마감없음/추출불가] %s", (r["title"] or "")[:48])
        else:
            found += 1
            log.info("  [마감 %s] %s", dl, (r["title"] or "")[:48])
        if not dry:
            try:
                with get_conn() as conn:
                    with conn.cursor() as cur:
                        if dl:
                            # deadline_at 비어있을 때만 채움(API 제공 마감 보존) + 검사함 표시
                            cur.execute(
                                """UPDATE announcement
                                   SET deadline_at = %s, deadline_checked_at = %s
                                   WHERE id = %s AND (deadline_at IS NULL OR deadline_at = '')""",
                                (dl, now_iso, r["id"]),
                            )
                        else:
                            # 마감 못 찾음 — 검사함만 표시(재처리 방지)
                            cur.execute(
                                "UPDATE announcement SET deadline_checked_at = %s WHERE id = %s",
                                (now_iso, r["id"]),
                            )
            except Exception:
                log.exception("  저장 실패 — %s", r["id"])
        time.sleep(0.2)  # Haiku 레이트리밋 보호

    log.info("완료 — 마감 추출 %d건 / 마감없음(null) %d건", found, none_cnt)
    return 0


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None, help="처리 최대 건수")
    ap.add_argument("--dry-run", action="store_true", help="DB 저장 없이 추출 결과만 출력")
    ap.add_argument("--force", action="store_true", help="이미 검사한(deadline_checked_at) 건도 재추출")
    args = ap.parse_args()
    print("=== 본문 마감일 추출 (deadline_at 백필) ===")
    return run(args.limit, args.dry_run, args.force)


if __name__ == "__main__":
    sys.exit(main())
