import json

d = json.load(open(r"D:\RFP-Targeter\data\raw\iitp-simulator-text.json", encoding="utf-8"))
pages = d["pages"]

for start, end, label in [
    (28, 35, "추진체계·역할분담"),
    (44, 56, "사업화·표준화·공개·보안조치"),
]:
    print(f"\n\n##### {label} (p{start}~{end}) #####")
    for p in pages[start - 1 : end]:
        if p["chars"] > 0:
            num = p["num"]
            print(f"\n--- p{num} ---")
            print(p["text"][:1400])
