"""슬랙 알림 안 온 이유 진단 — 80점+ 공고의 적합성/예산/발송여부."""
import json
import sys

sys.path.insert(0, "src")
from rfp_targeter.db.models import get_conn

with get_conn() as conn:
    cur = conn.cursor()
    cur.execute(
        """SELECT a.title, s.total_score, a.budget_mw, a.alerted_at, a.posted_at,
                  a.llm_assess_json, a.source
           FROM announcement a JOIN score s ON s.announcement_id = a.id
           WHERE a.is_security=TRUE AND a.is_dismissed=FALSE
             AND s.total_score >= 75
             AND (a.deadline_at >= CURRENT_DATE::text
                  OR (a.deadline_at IS NULL AND a.posted_at >= (CURRENT_DATE - 60)::text))
           ORDER BY s.total_score DESC"""
    )
    rows = cur.fetchall()

print(f"활성 75점+ 공고: {len(rows)}건\n")
print("슬랙 발송 조건: 적합성=high AND 예산≥1억(budget_mw≥100)\n")
for r in rows:
    j = json.loads(r["llm_assess_json"]) if r["llm_assess_json"] else {}
    rel = j.get("relevance") or "(미평가)"
    bud = r["budget_mw"]
    bud_ok = bud is not None and bud >= 100
    rel_ok = rel == "high"
    would_send = bud_ok and rel_ok
    sent = r["alerted_at"] is not None
    print(f"[{r['source']}] {r['total_score']:.0f}점 | 적합성={rel} | 예산={bud}(백만원) | posted={r['posted_at']}")
    print(f"   {r['title'][:52]}")
    print(f"   조건: 적합성high={rel_ok} 예산1억+={bud_ok} → 발송대상={would_send} / 실제발송={sent}")
    if would_send and not sent:
        print(f"   ⚠️ 발송 대상인데 안 됨 — 누락 의심!")
    elif not would_send:
        why = []
        if not rel_ok: why.append(f"적합성 {rel}(high 아님)")
        if not bud_ok: why.append("예산 1억 미만/없음")
        print(f"   ✓ 미발송 정상 — {', '.join(why)}")
    print()
