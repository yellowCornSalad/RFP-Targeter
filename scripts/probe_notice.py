"""사칭/주의 공지 공고 조사 — 왜 통과했나 + 비슷한 공지 전수."""
import sys

sys.path.insert(0, "src")
from rfp_targeter.db.models import get_conn

with get_conn() as conn:
    cur = conn.cursor()
    # 1. 문제 공고 — 사칭/사기/주의 제목
    cur.execute(
        """SELECT id, source, posted_at, is_security, is_dismissed, url,
                  matched_keywords_json, LEFT(body, 400) AS body_head, title
           FROM announcement
           WHERE (title LIKE '%사칭%' OR title LIKE '%사기피해%' OR title LIKE '%주의 안내%'
                  OR title LIKE '%[주의]%' OR title LIKE '%피해 예방%' OR title LIKE '%유의%')
           ORDER BY posted_at DESC"""
    )
    rows = cur.fetchall()
    print(f"=== 사칭/주의/안내 제목 공고: {len(rows)}건 ===")
    for r in rows:
        print(f"\n[{r['source']}] {r['posted_at']} sec={r['is_security']} dismissed={r['is_dismissed']}")
        print(f"  id={r['id']}")
        print(f"  title: {r['title']}")
        print(f"  매칭kw: {r['matched_keywords_json']}")
        print(f"  url: {r['url']}")
        print(f"  body앞: {(r['body_head'] or '')[:200]}")
