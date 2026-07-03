"""새 게이트 기준 '앞으로 슬랙 발송될 후보' 시뮬 — alerted NULL + 게이트 통과."""
import json
import sys

sys.path.insert(0, "src")
from rfp_targeter.db.models import get_conn

NOISE_DT = {"award", "hr", "event", "notice"}
EXC = ("수요기업", "공급기업", "참여기업", "사업자 모집")

with get_conn() as conn:
    cur = conn.cursor()
    cur.execute(
        """SELECT a.title, a.budget_mw, a.llm_assess_json, s.total_score
           FROM announcement a JOIN score s ON s.announcement_id=a.id
           WHERE a.is_security=TRUE AND a.is_dismissed=FALSE AND a.alerted_at IS NULL
             AND a.budget_mw IS NOT NULL AND a.budget_mw >= 100
             AND (a.deadline_at >= CURRENT_DATE::text
                  OR (a.deadline_at IS NULL AND a.posted_at >= (CURRENT_DATE - 60)::text))
           ORDER BY a.posted_at DESC"""
    )
    rows = cur.fetchall()

send, blocked = [], []
for r in rows:
    j = json.loads(r["llm_assess_json"]) if r["llm_assess_json"] else {}
    rel, dt, bd = j.get("relevance"), j.get("doc_type"), j.get("biddable")
    ok = rel == "high" and bd is not False
    if ok and dt in NOISE_DT and not any(k in (r["title"] or "") for k in EXC):
        ok = False
    (send if ok else blocked).append((r["title"], dt, rel, bd, r["total_score"]))

print(f"예산 1억+ 미발송(alerted NULL) 후보: {len(rows)}건")
print(f"→ 새 게이트로 슬랙 발송: {len(send)}건 / 차단: {len(blocked)}건\n")
print("=== 앞으로 슬랙 발송될 것 (high+응찰가능+예산1억+) ===")
for t, dt, rel, bd, sc in send:
    print(f"  [{dt} {rel} bid={bd}] {sc:.0f}점 | {(t or '')[:46]}")
