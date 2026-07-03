import json
import sys

sys.path.insert(0, "src")
from rfp_targeter.db.models import get_conn

pats = ["%성과기업 후속 지원%", "%수출지향형(함께달리기%"]
with get_conn() as conn:
    cur = conn.cursor()
    for pat in pats:
        cur.execute(
            "SELECT title, budget_mw, alerted_at, is_dismissed, llm_assess_json "
            "FROM announcement WHERE title LIKE %s ORDER BY posted_at DESC LIMIT 1",
            (pat,),
        )
        r = cur.fetchone()
        if not r:
            print(pat, "→ 없음\n")
            continue
        j = json.loads(r["llm_assess_json"]) if r["llm_assess_json"] else {}
        print("제목:", (r["title"] or "")[:50])
        print("  예산:", r["budget_mw"], "| alerted:", str(r["alerted_at"])[:16],
              "| dismissed:", r["is_dismissed"])
        print("  doc_type:", j.get("doc_type"), "| biddable:", j.get("biddable"),
              "| relevance:", j.get("relevance"))
        print("  reason:", (j.get("biddable_reason") or "")[:70])
        print()
