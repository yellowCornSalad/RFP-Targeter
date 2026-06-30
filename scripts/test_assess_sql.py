"""assess_contents SELECT 쿼리만 로컬 검증 — psycopg % 이스케이프 에러 없는지 + 대상 건수."""
import sys

sys.path.insert(0, "src")
from rfp_targeter.db.models import get_conn

where_extra = "AND (llm_assess_json IS NULL OR llm_assess_json NOT LIKE '%%biddable%%')"

with get_conn() as conn:
    with conn.cursor() as cur:
        cur.execute(
            f"""SELECT id, title FROM announcement
                WHERE is_security = TRUE AND is_dismissed = FALSE
                  AND (deadline_at >= CURRENT_DATE::text
                       OR (deadline_at IS NULL AND posted_at >= (CURRENT_DATE - 60)::text))
                  {where_extra}
                ORDER BY posted_at DESC NULLS LAST
                LIMIT %s""",
            (200,),
        )
        rows = cur.fetchall()

print(f"SQL OK — 재평가 대상(biddable 미포함 + NULL): {len(rows)}건")
for r in rows[:15]:
    print(f"  {(r['title'] or '')[:50]}")
