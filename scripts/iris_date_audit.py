"""IRIS posted_at 전수 감사 — 원본 ancmDe 대조."""
import json
import re
import sys
import time

import requests

BASE = "https://www.iris.go.kr"
LIST_URL = f"{BASE}/contents/retrieveBsnsAncmBtinSituList.do"
DETAIL_URL = f"{BASE}/contents/retrieveBsnsAncmView.do"

AUDIT = r"D:\RFP-Targeter\data\raw\audit\iris.json"


def to_iso(s):
    if not s:
        return None
    m = re.match(r"(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})", s.strip())
    if not m:
        return None
    return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"


def main():
    with open(AUDIT, encoding="utf-8") as f:
        rows = json.load(f)

    # target ancmId set (strip 'iris-' prefix)
    targets = {}
    for r in rows:
        ancm_id = r["external_id"].replace("iris-", "")
        targets[ancm_id] = r

    s = requests.Session()
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    })
    # warmup
    try:
        s.get(f"{BASE}/contents/retrieveBsnsAncmBtinSituListView.do", timeout=30)
    except Exception as e:
        print("warmup fail:", e, file=sys.stderr)

    found = {}  # ancmId -> ancmDe (raw)
    # scan list pages until all targets found or pages exhausted
    for page in range(1, 60):
        if len(found) >= len(targets):
            break
        try:
            r = s.post(
                LIST_URL,
                data={
                    "pageIndex": page,
                    "ancmSttArr": "",
                    "pbofrTpArr": "",
                    "blngGovdSeArr": "",
                    "sorgnIdArr": "",
                },
                headers={
                    "X-Requested-With": "XMLHttpRequest",
                    "Referer": f"{BASE}/contents/retrieveBsnsAncmBtinSituListView.do",
                },
                timeout=60,
            )
            r.raise_for_status()
            j = r.json()
        except Exception as e:
            print(f"page {page} fail: {e}", file=sys.stderr)
            break
        items = j.get("listBsnsAncmBtinSitu") or []
        if not items:
            print(f"page {page}: no items, stop", file=sys.stderr)
            break
        for it in items:
            aid = str(it.get("ancmId") or "")
            if aid in targets and aid not in found:
                found[aid] = {
                    "ancmDe": it.get("ancmDe"),
                    "ancmTl": it.get("ancmTl"),
                    "rcveStrDe": it.get("rcveStrDe"),
                    "rcveEndDe": it.get("rcveEndDe"),
                }
        print(f"page {page}: scanned {len(items)}, found {len(found)}/{len(targets)}",
              file=sys.stderr)
        time.sleep(0.8)

    # For any not found in list, try detail page scrape
    detail_found = {}
    for aid, row in targets.items():
        if aid in found:
            continue
        url = f"{DETAIL_URL}?ancmId={aid}&ancmPrg=ancmPre"
        try:
            r = s.get(url, timeout=60)
            r.raise_for_status()
            html = r.text
            # try to find a date label near 공고일 / 게시일
            detail_found[aid] = html
            print(f"detail fetch {aid}: {len(html)} bytes", file=sys.stderr)
        except Exception as e:
            print(f"detail {aid} fail: {e}", file=sys.stderr)
            detail_found[aid] = None
        time.sleep(0.8)

    # build result
    results = []
    for aid, row in targets.items():
        entry = {
            "id": row["id"],
            "title": row["title"],
            "posted_at": row["posted_at"],
            "ancmId": aid,
        }
        if aid in found:
            raw = found[aid]["ancmDe"]
            entry["raw_ancmDe"] = raw
            entry["site_date"] = to_iso(raw)
            entry["source_of_truth"] = "list_api_ancmDe"
        else:
            entry["raw_ancmDe"] = None
            entry["site_date"] = None
            entry["detail_html_len"] = len(detail_found.get(aid) or "") if detail_found.get(aid) else 0
            entry["source_of_truth"] = "detail_fallback"
        results.append(entry)

    print(json.dumps({"results": results}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
