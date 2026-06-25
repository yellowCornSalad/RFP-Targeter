"""MSS 활성 공고 날짜 전수 감사 — posted_at vs 원본 상세 페이지 등록일."""
from __future__ import annotations

import json
import time
from datetime import date
from pathlib import Path

from rfp_targeter.crawlers.mss import MSSCrawler

AUDIT = Path("data/raw/audit/mss.json")


def diff_days(a: str, b: str) -> int:
    ya, ma, da = (int(x) for x in a.split("-"))
    yb, mb, db = (int(x) for x in b.split("-"))
    return (date(ya, ma, da) - date(yb, mb, db)).days


def main() -> None:
    rows = json.loads(AUDIT.read_text(encoding="utf-8"))
    out = []
    for i, r in enumerate(rows, 1):
        site_date = None
        err = None
        for attempt in range(2):
            try:
                site_date = MSSCrawler._scrape_posted_date(r["url"])
            except Exception as e:  # noqa
                err = repr(e)
                site_date = None
            if site_date:
                break
            time.sleep(1.0)
        rec = {
            "id": r["id"],
            "title": r["title"],
            "posted_at": r["posted_at"],
            "site_date": site_date,
            "err": err,
        }
        if site_date and site_date != r["posted_at"]:
            rec["diff_days"] = diff_days(r["posted_at"], site_date)
        out.append(rec)
        print(f"[{i:2d}/20] {r['id']}  posted={r['posted_at']}  site={site_date}  {err or ''}")
        time.sleep(0.7)

    Path("data/raw/audit/_mss_result.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    checked = sum(1 for x in out if x["site_date"])
    mism = [x for x in out if x["site_date"] and x["site_date"] != x["posted_at"]]
    unreach = [x for x in out if not x["site_date"]]
    print(f"\nTOTAL={len(out)} CHECKED={checked} MISMATCH={len(mism)} UNREACHABLE={len(unreach)}")


if __name__ == "__main__":
    main()
