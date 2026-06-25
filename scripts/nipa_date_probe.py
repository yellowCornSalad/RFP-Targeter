"""NIPA 16814/16817 상세 페이지 + 목록 행 구조 직접 확인 — 진짜 작성일 확정."""
import re
import sys

import requests
import urllib3
from bs4 import BeautifulSoup

urllib3.disable_warnings()
sys.path.insert(0, "src")

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

# 1. 상세 페이지 — 진짜 작성일
for nid in ["16814", "16817"]:
    url = f"https://www.nipa.kr/home/2-2/{nid}"
    try:
        r = requests.get(url, timeout=30, verify=False, headers=UA)
        soup = BeautifulSoup(r.text, "lxml")
        infodt = soup.select_one(".infoDt")
        infodt_txt = infodt.get_text(" ", strip=True) if infodt else None
        # '작성일' 라벨 주변
        label = re.search(r"작성일[^0-9]{0,30}(\d{4}[.\-]\d{1,2}[.\-]\d{1,2})", r.text)
        dates = re.findall(r"\d{4}[.\-]\d{1,2}[.\-]\d{1,2}", r.text)
        print(f"[상세 {nid}] status={r.status_code}")
        print(f"  .infoDt = {infodt_txt}")
        print(f"  '작성일' 라벨 주변 = {label.group(1) if label else None}")
        print(f"  페이지 내 날짜(앞6) = {dates[:6]}")
        print()
    except Exception as e:
        print(f"[상세 {nid}] FAIL: {e}\n")

# 2. 목록 행 구조 — 어댑터가 보는 td 들
list_url = "https://www.nipa.kr/home/2-2"
try:
    r = requests.get(list_url, timeout=30, verify=False, headers=UA)
    soup = BeautifulSoup(r.text, "lxml")
    rows = soup.select("table tbody tr") or soup.select("tbody tr") or soup.select("tr")
    print(f"=== 목록 페이지 행 {len(rows)}개 — 16814/16817 행의 td 분해 ===")
    for tr in rows:
        a = tr.find("a", href=re.compile(r"/(16814|16817)(?:\?|$|/)"))
        if not a:
            continue
        nid = re.search(r"/(16814|16817)", a.get("href", "")).group(1)
        tds = tr.find_all("td")
        print(f"\n[목록행 {nid}] td 개수={len(tds)}")
        for i, td in enumerate(tds):
            txt = td.get_text(" ", strip=True)
            print(f"  td[{i}]: {txt[:70]}")
except Exception as e:
    print(f"[목록] FAIL: {e}")
