"""biddable 판정 품질 검증 — 노이즈는 false, 정상 R&D는 true 인지."""
import json
import sys
from collections import Counter

sys.path.insert(0, "src")
from rfp_targeter.db.models import get_conn

with get_conn() as conn:
    cur = conn.cursor()
    # biddable 키가 들어간(=새 평가) 활성 공고
    cur.execute(
        "SELECT title, llm_assess_json FROM announcement "
        "WHERE llm_assess_json LIKE '%biddable%' AND is_dismissed=FALSE "
        "AND is_security=TRUE"
    )
    rows = cur.fetchall()

dt = Counter()
bd = Counter()
false_s, true_s = [], []
for r in rows:
    try:
        j = json.loads(r["llm_assess_json"])
    except Exception:
        continue
    dt[j.get("doc_type")] += 1
    bd[str(j.get("biddable"))] += 1
    title = (r["title"] or "")[:44]
    if j.get("biddable") is False:
        false_s.append((j.get("doc_type"), title, (j.get("biddable_reason") or "")[:48]))
    elif j.get("biddable") is True:
        true_s.append((j.get("doc_type"), title))

print(f"biddable 채워진 활성공고: {len(rows)}건")
print(f"doc_type 분포: {dict(dt)}")
print(f"biddable 분포: {dict(bd)}")

print(f"\n=== biddable=FALSE (제외 예정) {len(false_s)}건 — 진짜 노이즈인가? ===")
for d, t, why in false_s[:20]:
    print(f"  [{d:11s}] {t}")
    print(f"       └ {why}")

print(f"\n=== biddable=TRUE (유지) {len(true_s)}건 — 진짜 응찰 가능한가? ===")
for d, t in true_s[:20]:
    print(f"  [{d:11s}] {t}")
