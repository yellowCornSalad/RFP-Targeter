"""노출 공고 중복 분석 — 같은 사업이 여러 source 에 게시된 것 탐지."""
import json
import os
import re
import sys
from collections import defaultdict

sys.path.insert(0, "src")


def dedup_key(t: str) -> str:
    """공고 유형 접미사 + 괄호 + 공백 제거 → 같은 사업이면 같은 키."""
    t = t or ""
    t = re.sub(r"^[\[\(【][^\]\)】]*[\]\)】]\s*", "", t)   # 앞 [재공고] 등
    t = re.sub(r"[\(\[【][^\)\]】]*[\)\]】]", "", t)        # 중간/끝 괄호
    t = re.sub(r"(공고문|재공고|공고|공모전|공모|모집공고|모집|신청|선정계획|선정공고)\s*$",
               "", t.strip())
    t = re.sub(r"\s+", "", t)
    return t.lower()


d = json.load(open(os.environ["TEMP"] + "/final.json", encoding="utf-8"))
items = d["items"]

groups = defaultdict(list)
for it in items:
    groups[dedup_key(it.get("title") or "")].append(it)

dupes = {k: v for k, v in groups.items() if len(v) > 1}
print(f"노출 {len(items)}건 / 고유 사업 {len(groups)}건 / 중복 그룹 {len(dupes)}개\n")

for k, v in dupes.items():
    print(f"=== 중복 {len(v)}건 (키: {k[:40]}) ===")
    for it in v:
        sc = (it.get("scores") or {}).get("total")
        print(f"  [{it['source']:5s}] score={sc} att={len(it.get('attachments') or [])} "
              f"| {(it.get('title') or '')[:48]}")
    print()
