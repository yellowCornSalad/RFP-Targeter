"""미평가 공고 진단 — llm_assess_json 상태 + body 길이 + 평가 대상 조건."""
import sys

sys.path.insert(0, "src")
from rfp_targeter.db.models import get_conn

titles = [
    "%우수성과 50선%",
    "%한-체코 공동연구%",
    "%AI최고급신진연구자%",
    "%기술개발제품 시범구매%",
]

with get_conn() as conn:
    cur = conn.cursor()
    for pat in titles:
        cur.execute(
            "SELECT id, title, is_security, is_dismissed, deadline_at, posted_at, "
            "length(COALESCE(body,'')) AS blen, llm_assess_json "
            "FROM announcement WHERE title LIKE %s LIMIT 1",
            (pat,),
        )
        r = cur.fetchone()
        if not r:
            print(f"{pat}: 없음")
            continue
        print(f"[{(r['title'] or '')[:40]}]")
        print(f"  is_security={r['is_security']} dismissed={r['is_dismissed']} "
              f"deadline={r['deadline_at']} posted={r['posted_at']} body_len={r['blen']}")
        print(f"  llm_assess_json={r['llm_assess_json']}")
        print()

    # 평가 대상 조건 카운트 (assess_contents 와 동일)
    cur.execute(
        """SELECT COUNT(*) AS c FROM announcement
           WHERE is_security=TRUE AND is_dismissed=FALSE
             AND (deadline_at >= CURRENT_DATE::text
                  OR (deadline_at IS NULL AND posted_at >= (CURRENT_DATE - 60)::text))
             AND llm_assess_json IS NULL"""
    )
    print(f"평가 대상 중 llm_assess_json NULL: {cur.fetchone()['c']}건")
