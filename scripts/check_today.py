import sys

sys.path.insert(0, "src")

from rfp_targeter.crawlers.mss import MSSCrawler  # noqa
from rfp_targeter.crawlers.nipa import NIPACrawler  # noqa

print("import OK — mss.py / nipa.py 문법 정상")

from rfp_targeter.db.models import get_conn

with get_conn() as conn:
    cur = conn.cursor()
    cur.execute(
        "SELECT source, posted_at, title FROM announcement "
        "WHERE posted_at >= '2026-06-25' AND is_dismissed=FALSE ORDER BY posted_at"
    )
    rows = cur.fetchall()
    print(f"DB posted_at >= 2026-06-25 (활성): {len(rows)}건")
    for r in rows:
        print("  [{}] {} {}".format(r["source"], r["posted_at"], (r["title"] or "")[:38]))
