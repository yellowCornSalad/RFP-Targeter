"""활성 공고를 새 필터로 재평가 → is_security 갱신.

새 exclude_strict(사칭) + exclude_strict_title(결과발표/합격자) 반영.
통과 못하면 is_security=FALSE → 사이트/슬랙 자동 제외.

사용: python scripts/backfill_security.py [--apply]
"""
import sys

sys.path.insert(0, "src")
from rfp_targeter.db.models import get_conn
from rfp_targeter.filters.security_filter import SecurityFilter

APPLY = "--apply" in sys.argv
sf = SecurityFilter()

with get_conn() as conn:
    cur = conn.cursor()
    cur.execute(
        "SELECT id, title, summary, body, agency, is_security "
        "FROM announcement WHERE is_dismissed=FALSE"
    )
    rows = cur.fetchall()
    changes = []
    for r in rows:
        res = sf.check(r["title"], r["summary"] or "", r["body"] or "", agency=r["agency"])
        if bool(r["is_security"]) != res.passed:
            changes.append((r["id"], bool(r["is_security"]), res.passed,
                            (r["title"] or "")[:46], res.excluded_by))
            if APPLY:
                cur.execute(
                    "UPDATE announcement SET is_security=%s WHERE id=%s",
                    (res.passed, r["id"]),
                )
    if APPLY:
        conn.commit()

removed = [c for c in changes if c[1] and not c[2]]   # TRUE -> FALSE (제거)
added = [c for c in changes if not c[1] and c[2]]      # FALSE -> TRUE (복구)

print(f"=== 재평가 {len(rows)}건 / 변경 {len(changes)}건 ({'APPLIED' if APPLY else 'DRY-RUN'}) ===")
print(f"제거 (TRUE->FALSE): {len(removed)}건")
for cid, _o, _n, title, exc in removed[:25]:
    print(f"  - {title} | by={exc}")
if len(removed) > 25:
    print(f"  ... 외 {len(removed) - 25}건")
print(f"\n복구/신규 (FALSE->TRUE): {len(added)}건")
for cid, _o, _n, title, exc in added[:25]:
    print(f"  + {title}")
