"""LLM 도메인 적합성 + TRL 맥락 평가 생성 → announcement.llm_assess_json 캐시.

[2026-06-01 사용자 요청] 키워드 단순 매칭 한계 보완 — 본문을 LLM(Haiku)이 읽고
(1) 실제 TRL 단계 (2) 회사 도메인 적합성(high/medium/low/none) 판단.

- build_summaries.yml 가 audit_contents.py 다음에 호출 (CI 에 ANTHROPIC_API_KEY).
- llm_assess_json IS NULL 인 활성 보안 공고만 평가 (--force 면 전체 재생성).
- 1건 ~$0.002 (Haiku). 결과는 DB 캐시 — 1회 생성 후 재사용.

실행:
    python scripts/assess_contents.py --limit 50      # NULL 만 (기본)
    python scripts/assess_contents.py --force          # 전체 재생성
    python scripts/assess_contents.py --limit 5 --dry-run   # 저장 없이 출력만
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rfp_targeter.db.models import get_conn, init_db  # noqa: E402
from rfp_targeter.llm_assess import assess_announcement  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger("assess_contents")


def run(limit: int, force: bool, dry: bool) -> int:
    init_db()  # llm_assess_json 컬럼 보장
    where_extra = "" if force else "AND llm_assess_json IS NULL"
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""SELECT id, title, body FROM announcement
                    WHERE is_security = TRUE AND is_dismissed = FALSE
                      AND body IS NOT NULL AND length(body) > 200
                      AND (deadline_at >= CURRENT_DATE::text
                           OR (deadline_at IS NULL AND posted_at >= (CURRENT_DATE - 60)::text))
                      {where_extra}
                    ORDER BY posted_at DESC NULLS LAST
                    LIMIT %s""",
                (limit,),
            )
            rows = cur.fetchall()

    log.info("평가 대상 %d건 (limit=%d, force=%s, dry=%s)", len(rows), limit, force, dry)
    ok, none_cnt = 0, 0
    for r in rows:
        res = assess_announcement(r["title"], r["body"])
        if res is None:
            none_cnt += 1
            log.warning("  assess None — %s", (r["title"] or "")[:42])
            continue
        log.info(
            "  [적합성 %-6s · trl %s] %s",
            res["relevance"], res["trl"], (r["title"] or "")[:45],
        )
        if dry:
            continue
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE announcement SET llm_assess_json=%s WHERE id=%s",
                        (json.dumps(res, ensure_ascii=False), r["id"]),
                    )
            ok += 1
        except Exception:
            log.exception("  저장 실패 — %s", r["id"])

    log.info("완료 — 저장 %d건 / assess 실패(None) %d건", ok, none_cnt)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=50)
    ap.add_argument("--force", action="store_true", help="llm_assess_json 있는 row 도 재생성")
    ap.add_argument("--dry-run", action="store_true", help="DB 저장 없이 출력만")
    a = ap.parse_args()
    return run(a.limit, a.force, a.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
