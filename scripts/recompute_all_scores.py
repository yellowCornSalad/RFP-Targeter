"""전체 활성 보안 공고 점수 강제 재계산.

용도: keyword.py 같은 점수 공식 수정 후 기존 score 들을 새 공식으로 재계산.
backfill_scores.py 는 score 가 NULL 인 경우만 처리하므로, 공식 변경 시엔 이 스크립트 필요.

사용:
    python scripts/recompute_all_scores.py              # 활성 보안만 (권장)
    python scripts/recompute_all_scores.py --all        # is_security=TRUE 전체
    python scripts/recompute_all_scores.py --dry-run    # 시뮬레이션만 (DB 업데이트 X)
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import Counter

from rfp_targeter.db.models import Announcement, get_conn, upsert_score
from rfp_targeter.scoring import compute_score

log = logging.getLogger("recompute_scores")


_ANN_ALLOWED = {
    "source", "external_id", "title", "url", "agency",
    "posted_at", "deadline_at", "budget_mw", "duration_months",
    "budget_period", "budget_excerpt", "budget_confidence",
    "summary", "body", "is_security",
    "eligibility_status", "eligibility_note", "eligibility_limit",
    "application_start_date",
}


def _row_to_announcement(r: dict) -> Announcement:
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


def _bucket(score: float) -> str:
    if score >= 95: return "95-100"
    if score >= 85: return "85-94"
    if score >= 70: return "70-84"
    if score >= 55: return "55-69"
    if score >= 40: return "40-54"
    if score >= 25: return "25-39"
    return "0-24"


def recompute(active_only: bool, dry_run: bool) -> tuple[int, int]:
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
                SELECT a.*, s.keyword_score AS old_kw, s.total_score AS old_total
                FROM announcement a
                LEFT JOIN score s ON s.announcement_id = a.id
                WHERE a.is_security = TRUE
                  AND a.is_dismissed = FALSE
                  {where_extra}
                ORDER BY a.posted_at DESC NULLS LAST
                """
            )
            rows = cur.fetchall()

    log.info("재계산 대상 %d건 — %s", len(rows), "DRY-RUN" if dry_run else "실제 update")

    old_kw_dist = Counter()
    new_kw_dist = Counter()
    old_total_dist = Counter()
    new_total_dist = Counter()
    changes_top = []  # (delta, title, old_kw, new_kw, old_total, new_total)

    ok, fail = 0, 0
    for r in rows:
        try:
            a = _row_to_announcement(r)
            # 🤖 LLM 도메인 적합성·TRL 판단 반영 (있으면)
            try:
                _llm = json.loads(r.get("llm_assess_json") or "{}")
                _llm = _llm if isinstance(_llm, dict) and _llm else None
            except Exception:
                _llm = None
            sc = compute_score(a, llm=_llm)

            old_kw = float(r.get("old_kw") or 0)
            old_total = float(r.get("old_total") or 0)
            old_kw_dist[_bucket(old_kw)] += 1
            new_kw_dist[_bucket(sc.keyword_score)] += 1
            old_total_dist[_bucket(old_total)] += 1
            new_total_dist[_bucket(sc.total_score)] += 1

            delta = abs(sc.keyword_score - old_kw)
            if delta >= 5:
                changes_top.append((delta, a.title[:60], old_kw, sc.keyword_score, old_total, sc.total_score))

            if not dry_run:
                with get_conn() as conn:
                    upsert_score(conn, sc)
            ok += 1
            if ok % 100 == 0:
                log.info("  진행 %d/%d", ok, len(rows))
        except Exception as e:
            fail += 1
            log.warning("FAIL %s: %s", r.get("id"), e)

    # ── 분포 비교 ──
    print("\n" + "=" * 70)
    print("📊 keyword_score 분포 변화")
    print("=" * 70)
    print(f"{'구간':>10} | {'이전':>8} | {'이후':>8} | {'증감':>8}")
    print("-" * 50)
    buckets = ["95-100", "85-94", "70-84", "55-69", "40-54", "25-39", "0-24"]
    for b in buckets:
        old_n = old_kw_dist.get(b, 0)
        new_n = new_kw_dist.get(b, 0)
        diff = new_n - old_n
        arrow = "↑" if diff > 0 else ("↓" if diff < 0 else "·")
        print(f"  {b:>8} | {old_n:>8} | {new_n:>8} | {arrow}{abs(diff):>6}")
    total = sum(new_kw_dist.values())
    top10pct = new_kw_dist.get("95-100", 0)
    print(f"\n  95-100점 (만점급): {top10pct}건 / {total}건 = {100*top10pct/max(1,total):.1f}%")

    print("\n" + "=" * 70)
    print("📊 total_score 분포 변화")
    print("=" * 70)
    print(f"{'구간':>10} | {'이전':>8} | {'이후':>8} | {'증감':>8}")
    print("-" * 50)
    for b in buckets:
        old_n = old_total_dist.get(b, 0)
        new_n = new_total_dist.get(b, 0)
        diff = new_n - old_n
        arrow = "↑" if diff > 0 else ("↓" if diff < 0 else "·")
        print(f"  {b:>8} | {old_n:>8} | {new_n:>8} | {arrow}{abs(diff):>6}")

    # ── 변화 큰 공고 top 10 ──
    print("\n" + "=" * 70)
    print("🔍 keyword_score 변화 큰 공고 top 10")
    print("=" * 70)
    changes_top.sort(reverse=True)
    for delta, title, okw, nkw, ot, nt in changes_top[:10]:
        print(f"  Δ{delta:5.1f}  kw {okw:5.1f}→{nkw:5.1f}  total {ot:5.1f}→{nt:5.1f}  {title}")

    log.info("\n완료: 성공 %d / 실패 %d", ok, fail)
    return ok, fail


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true", help="활성 필터 무시, is_security=TRUE 전체")
    ap.add_argument("--dry-run", action="store_true", help="DB 업데이트 안 함, 분포만 출력")
    args = ap.parse_args()
    ok, fail = recompute(active_only=not args.all, dry_run=args.dry_run)
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
