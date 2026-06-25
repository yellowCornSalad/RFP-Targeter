"""NIPA 상세 페이지 게시일(작성일) 전수 추출 → posted_at 대조."""
import json, re, time, sys
import requests
from bs4 import BeautifulSoup

AUDIT = r"D:\RFP-Targeter\data\raw\audit\nipa.json"
HDR = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

def extract_site_date(html: str):
    soup = BeautifulSoup(html, "lxml")
    # 1차: <span class="infoDt"> 작성일
    el = soup.select_one("span.infoDt")
    if el:
        m = re.search(r"(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})", el.get_text(" ", strip=True))
        if m:
            return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}", "infoDt"
    # 2차 폴백: '작성일'/'등록일' 라벨 주변 날짜
    for el in soup.find_all(string=re.compile(r"작성일|등록일|게시일")):
        ctx = el.parent.get_text(" ", strip=True) if el.parent else str(el)
        m = re.search(r"(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})", ctx)
        if m:
            return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}", "label"
    return None, "none"

def main():
    items = json.load(open(AUDIT, encoding="utf-8"))
    results = []
    for i, it in enumerate(items):
        rec = {"id": it["id"], "title": it["title"], "posted_at": it["posted_at"],
               "url": it["url"], "site_date": None, "extractor": None, "error": None}
        try:
            r = requests.get(it["url"], headers=HDR, timeout=60)
            if r.status_code != 200:
                rec["error"] = f"HTTP {r.status_code}"
            else:
                sd, ext = extract_site_date(r.text)
                rec["site_date"] = sd
                rec["extractor"] = ext
                if sd is None:
                    rec["error"] = "no_date_found"
        except Exception as e:
            rec["error"] = f"{type(e).__name__}: {e}"
        results.append(rec)
        print(f"[{i+1}/{len(items)}] {it['id']} posted={it['posted_at']} site={rec['site_date']} ({rec['extractor']}) err={rec['error']}", flush=True)
        time.sleep(1.2)

    out = r"D:\RFP-Targeter\data\raw\audit\nipa_dates_result.json"
    json.dump(results, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("\n=== SUMMARY ===")
    match = mismatch = unreach = 0
    for rec in results:
        if rec["site_date"] is None:
            unreach += 1
        elif rec["site_date"] == rec["posted_at"]:
            match += 1
        else:
            mismatch += 1
            print(f"MISMATCH {rec['id']}: posted={rec['posted_at']} site={rec['site_date']}")
    print(f"match={match} mismatch={mismatch} unreachable={unreach} total={len(results)}")

if __name__ == "__main__":
    main()
