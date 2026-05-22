"""모든 공고 본문 → AI 1~2문장 요약 → DB ai_summary 컬럼에 저장.

사용:
    python scripts/generate_summaries.py              # 비어있는 것만
    python scripts/generate_summaries.py --regen      # 전체 재생성
    python scripts/generate_summaries.py --source kisa --limit 20

비용 추정 (claude-haiku-4-5):
- 입력 ~3000자 × $1/1M tokens × 700건 ≈ $2
- 출력 ~150자 × $5/1M tokens × 700건 ≈ $0.5
- 총 ~$3 (전체 1회 생성)
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rfp_targeter.db.models import get_conn, init_db  # noqa: E402
from rfp_targeter.drafter.summarizer import summarize_announcement  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default=None, help="단일 source만")
    ap.add_argument("--limit", type=int, default=None, help="최대 N건")
    ap.add_argument("--regen", action="store_true", help="기존 요약 무시하고 재생성")
    ap.add_argument("--sleep", type=float, default=0.5, help="요청 간 sleep (rate limit)")
    args = ap.parse_args()

    logging.basicConfig(level=logging.WARNING, format="%(message)s")
    init_db()

    where = ["is_security = TRUE", "body IS NOT NULL", "LENGTH(body) > 100"]
    params = []
    if not args.regen:
        where.append("(ai_summary IS NULL OR ai_summary = '')")
    if args.source:
        where.append("source = %s")
        params.append(args.source)

    sql = f"""SELECT id, source, external_id, title, body
              FROM announcement
              WHERE {' AND '.join(where)}
              ORDER BY posted_at DESC NULLS LAST"""
    if args.limit:
        sql += f" LIMIT {args.limit}"

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()

    print(f"대상: {len(rows):,}건")
    ok, skip, fail = 0, 0, 0
    for i, r in enumerate(rows, 1):
        s = summarize_announcement(r["title"] or "", r["body"] or "")
        if not s:
            skip += 1
            continue
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE announcement SET ai_summary=%s WHERE id=%s",
                        (s, r["id"]),
                    )
            ok += 1
            if i % 10 == 0 or i == len(rows):
                print(f"  [{i:4d}/{len(rows)}] OK {ok} · SKIP {skip} · FAIL {fail}")
                print(f"    ex: {s[:100]}")
        except Exception as e:
            fail += 1
            print(f"  [{i:4d}] update fail: {e}")
        time.sleep(args.sleep)

    print(f"\n완료: 생성 {ok}건 / 건너뜀 {skip}건 / 실패 {fail}건")


if __name__ == "__main__":
    main()
