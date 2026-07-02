import json
from collections import Counter

with open("site/data.json", encoding="utf-8") as f:
    d = json.load(f)

iris = [i for i in d["items"] if i["source"] == "iris"]
print(f"IRIS site items: {len(iris)}")
print()

all_kw = Counter()
for it in iris:
    for k in it.get("matched_keywords", []):
        all_kw[k] += 1

print("매칭 키워드 TOP 15:")
for k, n in all_kw.most_common(15):
    print(f"  {n:3d}건 - {k}")
print()

print("샘플 5건 (제목·매칭):")
for it in iris[:5]:
    title = it["title"][:60]
    matched = it.get("matched_keywords", [])[:6]
    print(f"  - {title}")
    print(f"    매칭: {matched}")
