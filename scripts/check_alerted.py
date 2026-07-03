"""슬랙으로 발송된(alerted_at NOT NULL) 공고 중 노이즈(biddable=false/doc_type) 확인."""
import json
import sys

sys.path.insert(0, "src")
from rfp_targeter.db.models import get_conn

with get_conn() as conn:
    cur = conn.cursor()
    cur.execute(
        """SELECT a.title, a.alerted_at, a.budget_mw, a.llm_assess_json, s.total_score
           FROM announcement a JOIN score s ON s.announcement_id = a.id
           WHERE a.alerted_at IS NOT NULL
           ORDER BY a.alerted_at DESC
           LIMIT 25"""
    )
    rows = cur.fetchall()

print(f"슬랙 발송된 공고 (최근 25): {len(rows)}건\n")
noise = 0
for r in rows:
    j = json.loads(r["llm_assess_json"]) if r["llm_assess_json"] else {}
    dt = j.get("doc_type") or "(미평가)"
    rel = j.get("relevance") or "?"
    bd = j.get("biddable")
    is_noise = (bd is False) or (dt in ("award", "hr", "event", "notice"))
    mark = "  ❌ 노이즈" if is_noise else "  ✅ 정상"
    if is_noise:
        noise += 1
    print(f"[{dt:11s} rel={rel:6s} bid={bd}] {r['total_score']:.0f}점 예산={r['budget_mw']}"
          f"{mark}")
    print(f"   {(r['title'] or '')[:55]}  (발송 {str(r['alerted_at'])[:16]})")
print(f"\n노이즈 발송: {noise}/{len(rows)}건")
