"""rfp_contents 스킬 — 공고 콘텐츠 5축 점검 + LLM 카드 요약 생성.

수동:
    python scripts/audit_contents.py            # 점검 + ai_summary NULL 만 생성
    python scripts/audit_contents.py --force    # 활성 전체 재생성
    python scripts/audit_contents.py --audit-only  # 요약 생성 안 함, 점검만
    python scripts/audit_contents.py --limit 50 # 처리 최대 건수 제한
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rfp_targeter.config import secrets  # noqa: E402
from rfp_targeter.db.models import get_conn  # noqa: E402

log = logging.getLogger("audit_contents")

SUMMARY_MODEL = "claude-haiku-4-5"
SUMMARY_MAX_TOKENS = 200
SUMMARY_SYSTEM = (
    "당신은 한국 정부 R&D 공고를 카드에 표시할 짧은 요약을 만드는 전문가다. "
    "본문과 첨부 텍스트를 종합해 150자 이내 한국어로 요약하라. "
    "포함: 사업 본질·대상·예산·핵심 활동. "
    "제외: 안내문구, 자격요건, 행정 절차, 인사말. "
    "딱 한 문단으로 마침표까지 끝내라. 절대 150자 넘기지 마라."
)


def _get_anthropic_client():
    """Anthropic SDK 클라이언트. 미설치 / 키 없으면 None."""
    key = (
        os.environ.get("ANTHROPIC_API_KEY")
        or (secrets().get("anthropic") or {}).get("api_key")
        or ""
    ).strip()
    if not key or key == "???":
        log.warning("ANTHROPIC_API_KEY 미설정 — 요약 생성 skip")
        return None
    try:
        from anthropic import Anthropic
    except ImportError:
        log.warning("anthropic SDK 미설치 — `pip install anthropic`")
        return None
    return Anthropic(api_key=key)


def audit_quality() -> dict:
    """5축 점검 — SQL 만으로 빠르게. Returns 통계 dict."""
    stats: dict = {}
    with get_conn() as c:
        with c.cursor() as cur:
            # 활성 보안 공고 기본 통계
            cur.execute(
                """SELECT COUNT(*) AS total,
                          COUNT(*) FILTER (WHERE ai_summary IS NOT NULL) AS has_summary,
                          COUNT(*) FILTER (WHERE budget_mw IS NOT NULL) AS has_budget,
                          COUNT(*) FILTER (WHERE budget_period IS NOT NULL) AS has_period,
                          COUNT(*) FILTER (WHERE LENGTH(COALESCE(body,'')) >= 300) AS body_ge_300,
                          COUNT(*) FILTER (WHERE body LIKE %s) AS has_head_token,
                          COUNT(*) FILTER (WHERE body LIKE %s) AS att_in_body
                   FROM announcement
                   WHERE is_security=TRUE AND is_dismissed=FALSE
                     AND source IN ('iitp','kisa','krit','nipa','mss','koica')
                     AND (deadline_at >= CURRENT_DATE::text
                          OR (deadline_at IS NULL
                              AND posted_at >= (CURRENT_DATE - 60)::text))""",
                ("%§§HEAD§§%", "%[첨부 본문]%"),
            )
            r = cur.fetchone()
            stats["active_total"] = r["total"]
            stats["has_summary"] = r["has_summary"]
            stats["has_budget"] = r["has_budget"]
            stats["has_period"] = r["has_period"]
            stats["body_ge_300"] = r["body_ge_300"]
            stats["has_head_token"] = r["has_head_token"]
            stats["att_in_body"] = r["att_in_body"]

            # source별 첨부 통합률 / 평균 매칭 키워드
            cur.execute(
                """SELECT source, COUNT(*) AS total,
                          COUNT(*) FILTER (WHERE body LIKE %s) AS att_in_body,
                          AVG(LENGTH(COALESCE(body,''))) AS avg_body_len,
                          AVG(jsonb_array_length(matched_keywords_json::jsonb)) AS avg_kw
                   FROM announcement
                   WHERE is_security=TRUE AND is_dismissed=FALSE
                     AND source IN ('iitp','kisa','krit','nipa','mss','koica')
                     AND (deadline_at >= CURRENT_DATE::text
                          OR (deadline_at IS NULL
                              AND posted_at >= (CURRENT_DATE - 60)::text))
                   GROUP BY source""",
                ("%[첨부 본문]%",),
            )
            stats["by_source"] = list(cur.fetchall())
    return stats


def generate_summaries(force: bool = False, limit: int | None = None) -> tuple[int, int]:
    """ai_summary 생성. NULL 인 row 만 (force=True면 전체 재생성).

    Returns (성공, 실패)
    """
    client = _get_anthropic_client()
    if client is None:
        return 0, 0

    where_extra = "" if force else "AND ai_summary IS NULL"
    limit_clause = f"LIMIT {int(limit)}" if limit else ""
    with get_conn() as c:
        with c.cursor() as cur:
            cur.execute(
                f"""SELECT id, title, agency, body, attachments_json
                    FROM announcement
                    WHERE is_security=TRUE AND is_dismissed=FALSE
                      AND source IN ('iitp','kisa','krit','nipa','mss','koica')
                      AND (deadline_at >= CURRENT_DATE::text
                           OR (deadline_at IS NULL
                               AND posted_at >= (CURRENT_DATE - 60)::text))
                      AND LENGTH(COALESCE(body,'')) >= 300
                      {where_extra}
                    ORDER BY posted_at DESC NULLS LAST
                    {limit_clause}"""
            )
            rows = cur.fetchall()

    log.info("LLM 요약 생성 대상: %d건", len(rows))
    if not rows:
        return 0, 0

    ok, fail = 0, 0
    for i, r in enumerate(rows, 1):
        body = (r["body"] or "")[:6000]  # 토큰 비용 절감
        prompt = f"제목: {r['title']}\n발주: {r['agency'] or '미명시'}\n\n본문(첨부 포함):\n{body}"
        try:
            resp = client.messages.create(
                model=SUMMARY_MODEL,
                max_tokens=SUMMARY_MAX_TOKENS,
                system=SUMMARY_SYSTEM,
                messages=[{"role": "user", "content": prompt}],
            )
            summary = resp.content[0].text.strip()
            # 150자 하드 컷
            if len(summary) > 160:
                summary = summary[:157] + "..."
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE announcement SET ai_summary=%s WHERE id=%s",
                        (summary, r["id"]),
                    )
            ok += 1
            if i % 20 == 0:
                log.info("  진행 %d/%d", i, len(rows))
        except Exception as e:
            fail += 1
            log.warning("[%s] 요약 실패: %s", r["id"], str(e)[:80])
        # rate limit 보호 — Haiku 분당 ~50건
        time.sleep(0.2)

    return ok, fail


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="ai_summary 있는 row 도 재생성")
    ap.add_argument("--audit-only", action="store_true", help="점검만 수행, 요약 생성 X")
    ap.add_argument("--limit", type=int, default=None, help="처리 최대 건수")
    args = ap.parse_args()

    print("=== rfp_contents 콘텐츠 점검 + LLM 요약 ===\n")

    # 1) 5축 점검
    s = audit_quality()
    print(f"[활성 보안 공고] 총 {s['active_total']}건")
    print(f"  · ai_summary 보유율:  {100*s['has_summary']/max(s['active_total'],1):.0f}% ({s['has_summary']})")
    print(f"  · 예산 추출률:        {100*s['has_budget']/max(s['active_total'],1):.0f}% ({s['has_budget']})")
    print(f"  · 기간 추출률:        {100*s['has_period']/max(s['active_total'],1):.0f}% ({s['has_period']})")
    print(f"  · 본문 300자 이상:    {100*s['body_ge_300']/max(s['active_total'],1):.0f}% ({s['body_ge_300']})")
    print(f"  · 가독성 토큰(HEAD):  {100*s['has_head_token']/max(s['active_total'],1):.0f}% ({s['has_head_token']})")
    print(f"  · 첨부 본문 통합률:   {100*s['att_in_body']/max(s['active_total'],1):.0f}% ({s['att_in_body']})\n")

    print("[source별 통계]")
    print(f"  {'src':6s}  total  첨부통합  평균본문  평균매칭")
    for r in s["by_source"]:
        t = r["total"]
        a = r["att_in_body"]
        print(f"  {r['source']:6s}  {t:5d}  {100*a/t:5.1f}%   {int(r['avg_body_len']):6d}자  {float(r['avg_kw'] or 0):5.1f}")

    if args.audit_only:
        return 0

    # 2) LLM 요약 생성
    print("\n=== LLM 요약 생성 ===")
    ok, fail = generate_summaries(force=args.force, limit=args.limit)
    print(f"성공 {ok} / 실패 {fail}")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
