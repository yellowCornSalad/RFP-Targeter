"""게이트 최종 검증 — gh-pages 노출 공고를 DB와 대조.

biddable=false / relevance=none 이 노출에 새어나갔는지 + 남은 게 응찰 가능한지.
"""
import json
import os
import sys
import urllib.request
from collections import Counter

sys.path.insert(0, "src")
from rfp_targeter.db.models import get_conn

# gh-pages 원본 (CDN 우회)
url = "https://raw.githubusercontent.com/yellowCornSalad/RFP-Targeter/gh-pages/data.json"
data = json.loads(urllib.request.urlopen(url, timeout=30).read().decode("utf-8"))
items = data["items"]
ids = [it["id"] for it in items]
print(f"gh-pages build: {data.get('build_time')} | 노출: {len(items)}건\n")

# DB 에서 노출 공고들의 llm_assess_json 대조
leaks_bd, leaks_rel = [], []
dt_dist, bd_dist, rel_dist = Counter(), Counter(), Counter()
with get_conn() as conn:
    cur = conn.cursor()
    for cid in ids:
        cur.execute("SELECT title, llm_assess_json FROM announcement WHERE id=%s", (cid,))
        r = cur.fetchone()
        if not r:
            continue
        j = json.loads(r["llm_assess_json"]) if r["llm_assess_json"] else {}
        dt = j.get("doc_type")
        bd = j.get("biddable")
        rel = j.get("relevance")
        dt_dist[dt if dt else "(미평가)"] += 1
        bd_dist[str(bd)] += 1
        rel_dist[rel if rel else "(미평가)"] += 1
        if bd is False:
            leaks_bd.append((r["title"][:46], dt))
        if rel == "none":
            leaks_rel.append((r["title"][:46], dt))

print("=== 노출 공고 분포 ===")
print(f"  doc_type : {dict(dt_dist)}")
print(f"  biddable : {dict(bd_dist)}")
print(f"  relevance: {dict(rel_dist)}")

print(f"\n=== 게이트 누수 검사 ===")
print(f"  biddable=false 누수: {len(leaks_bd)}건 (0이어야)")
for t, dt in leaks_bd:
    print(f"    ! [{dt}] {t}")
print(f"  relevance=none 누수: {len(leaks_rel)}건 (0이어야)")
for t, dt in leaks_rel:
    print(f"    ! [{dt}] {t}")

print(f"\n=== 노출 공고 전체 (응찰 가능한가 육안 확인) ===")
with get_conn() as conn:
    cur = conn.cursor()
    for cid in ids:
        cur.execute("SELECT title, llm_assess_json FROM announcement WHERE id=%s", (cid,))
        r = cur.fetchone()
        if not r:
            continue
        j = json.loads(r["llm_assess_json"]) if r["llm_assess_json"] else {}
        dt = j.get("doc_type") or "(미평가)"
        bd = j.get("biddable")
        flag = "T" if bd is True else ("F" if bd is False else "?")
        print(f"  [{flag}|{dt:11s}] {(r['title'] or '')[:50]}")
