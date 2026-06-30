"""현재 홈페이지에서 필터링돼 안 보이는 공고 목록 — 제목 + 링크 + 사유.

노출 후보(is_security·활성·60일내) 중 실제 노출(site/data.json) 에 없는 것 = 숨김.
"""
import json
import sys
from collections import defaultdict

sys.path.insert(0, "src")
from rfp_targeter.db.models import get_conn

# 실제 노출 id (방금 로컬 빌드 = 라이브와 동일)
visible = {it["id"] for it in json.load(open("site/data.json", encoding="utf-8"))["items"]}

with get_conn() as conn:
    cur = conn.cursor()
    cur.execute(
        """SELECT id, title, url, llm_assess_json FROM announcement
           WHERE is_security=TRUE AND is_dismissed=FALSE
             AND source IN ('iitp','kisa','krit','nipa','mss','koica','iris')
             AND (deadline_at >= CURRENT_DATE::text
                  OR (deadline_at IS NULL AND posted_at >= (CURRENT_DATE - 60)::text))
           ORDER BY posted_at DESC"""
    )
    rows = cur.fetchall()

groups = defaultdict(list)
for r in rows:
    if r["id"] in visible:
        continue
    j = json.loads(r["llm_assess_json"]) if r["llm_assess_json"] else {}
    dt, rel, bd = j.get("doc_type"), j.get("relevance"), j.get("biddable")
    if rel == "none":
        reason = "회사 수행 불가 분야 (제조·바이오·반도체 등)"
    elif dt in ("award", "hr", "event"):
        reason = {"award": "시상·표창", "hr": "인력·연수 모집", "event": "행사·경진대회"}[dt]
    elif dt == "notice":
        reason = "공지·안내 (수요기업 모집 제외)"
    elif bd is False and rel == "low":
        reason = "응찰 불가 + 본업 거리 멈 (물품구매·성과분석 등)"
    else:
        reason = "중복 제거(같은 사업 타 기관) 또는 미평가"
    groups[reason].append((r["title"] or "", r["url"] or ""))

total = sum(len(v) for v in groups.values())
print(f"현재 안 보이는 공고: {total}건\n")
for reason, lst in sorted(groups.items(), key=lambda x: -len(x[1])):
    print(f"━━ {reason} — {len(lst)}건 ━━")
    for title, url in lst:
        print(f"  · {title[:60]}")
        print(f"    {url}")
    print()
