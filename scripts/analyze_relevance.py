"""현재 노출 공고의 LLM relevance 분포 + 비R&D 노이즈 유형 분석."""
import json
import os
from collections import Counter

d = json.load(open(os.environ["TEMP"] + "/ghp4.json", encoding="utf-8"))
items = d["items"]
print(f"노출 공고: {len(items)}건\n")

# 1. relevance 분포 (llm 필드)
rel_dist = Counter()
for it in items:
    llm = it.get("llm") or {}
    rel = llm.get("relevance") or "(미평가)"
    rel_dist[rel] += 1
print("=== LLM relevance 분포 ===")
for k, v in rel_dist.most_common():
    print(f"  {k}: {v}건")

# 2. 비R&D 노이즈 제목 패턴 (사용자 지적 유형)
NOISE = {
    "시상/추천": ["상 ", "수상", "추천", "시상", "포상", "표창", "공로", "유공"],
    "행사/세미나": ["세미나", "포럼", "설명회", "박람회", "행사", "워크숍", "컨퍼런스", "전시"],
    "인력/연수": ["연수생", "교육생", "인턴", "채용", "후보생", "수강생", "교육과정"],
    "용역/조사": ["실태조사", "만족도", "용역", "운영 대행", "위탁 운영"],
    "공지/안내": ["안내", "공지", "주의", "정정", "변경", "연기", "휴무"],
}
print("\n=== 비R&D 노이즈 유형 (제목 기준) ===")
for cat, pats in NOISE.items():
    hits = []
    for it in items:
        t = (it.get("title") or "")
        if any(p in t for p in pats):
            llm = it.get("llm") or {}
            hits.append((t[:42], llm.get("relevance") or "(미평가)",
                         (it.get("scores") or {}).get("total")))
    if hits:
        print(f"\n[{cat}] {len(hits)}건")
        for title, rel, sc in hits[:10]:
            print(f"  rel={rel:10s} score={sc} | {title}")
