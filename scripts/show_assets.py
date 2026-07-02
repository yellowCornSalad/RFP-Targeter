import json

d = json.load(open(r"D:\RFP-Targeter\data\raw\company_assets.json", encoding="utf-8"))

print("=== 국내 등록 24건 ===")
for p in d["patents"]["domestic_registered"]:
    title = p["title"]
    note = p.get("note", "")
    flag = " [ETRI양도]" if "양도" in note else ""
    print(f"  {p['no']}. ({p['reg_date'][:10]}) {title}{flag}")

print("\n=== 국내 출원중 6건 ===")
for p in d["patents"]["domestic_pending"]:
    print(f"  {p['no']}. ({p['app_date']}) {p['title']}")

print("\n=== 해외 등록 2건 + 출원 3건 ===")
for p in d["patents"]["foreign_registered"]:
    print(f"  R {p['app_no']} | {p['title']}")
for p in d["patents"]["foreign_pending"]:
    print(f"  P {p['app_no']} | {p['title']}")

print("\n=== 인증/SW 19건 ===")
from collections import defaultdict
by_type = defaultdict(list)
for c in d["certs"]:
    by_type[c["유형"]].append(c["기술명"])
for t, items in by_type.items():
    print(f"\n[{t}]")
    for it in items:
        print(f"  - {it}")
