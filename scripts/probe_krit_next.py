"""KRIT PMS 캐러셀 walk v3 — 실제 마우스 클릭으로 .portal_mtab_next 순회.

Nexacro 는 JS element.click() 무시 → Playwright page.mouse.click(x,y) (실제 이벤트) 필요.
next = .portal_mtab_next (id ...btnMtabNext)
"""
from __future__ import annotations

import sys
from playwright.sync_api import sync_playwright

URL = "https://pms.krit.re.kr/kritpmsi/nxui/kritpms/index.jsp"

EXTRACT_VISIBLE = """
() => {
    const cards = document.querySelectorAll(".portal_div_project");
    const out = [];
    for (const card of cards) {
        const cs = window.getComputedStyle(card);
        if (cs.display === "none" || cs.visibility === "hidden") continue;
        const r = card.getBoundingClientRect();
        if (r.width === 0 && r.height === 0) continue;
        const t = card.querySelector(".portal_sta_projTitle");
        const d = card.querySelector(".portal_sta_projDate");
        out.push({ title: t ? t.innerText.trim() : null, date: d ? d.innerText.trim() : null });
    }
    return out;
}
"""

READ_PAGE = """
() => {
    for (const el of document.querySelectorAll(".portal_mtab_page_S")) {
        const cs = window.getComputedStyle(el);
        if (cs.display === "none" || cs.visibility === "hidden") continue;
        const cur = el.innerText.trim();
        let total = "?";
        const p = el.parentElement;
        if (p) { const t = p.querySelector(".portal_mtab_page"); if (t) total = t.innerText.trim(); }
        return cur + " / " + total;
    }
    return "?";
}
"""

# 보이는 next 버튼의 중심 좌표 반환
NEXT_XY = """
() => {
    for (const el of document.querySelectorAll(".portal_mtab_next")) {
        const cs = window.getComputedStyle(el);
        if (cs.display === "none" || cs.visibility === "hidden") continue;
        const r = el.getBoundingClientRect();
        if (r.width === 0 && r.height === 0) continue;
        return { x: Math.round((r.left+r.right)/2), y: Math.round((r.top+r.bottom)/2) };
    }
    return null;
}
"""


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 900}, locale="ko-KR")
        page.goto(URL, wait_until="domcontentloaded")
        page.wait_for_timeout(5000)

        all_titles = []
        for step in range(7):
            pg = page.evaluate(READ_PAGE)
            cards = page.evaluate(EXTRACT_VISIBLE)
            print(f"--- step {step}: page {pg} — {len(cards)} visible ---")
            for c in cards:
                mark = "  <<STALE 2023" if (c["date"] and "2023" in c["date"]) else ""
                print(f"    {c['date']}  {c['title']}{mark}")
                all_titles.append(c["title"])

            xy = page.evaluate(NEXT_XY)
            if not xy:
                print("    [no visible next btn — stop]")
                break
            page.mouse.click(xy["x"], xy["y"])
            page.wait_for_timeout(1500)

        uniq = list(dict.fromkeys(all_titles))
        print(f"\n=== UNIQUE titles across walk: {len(uniq)} ===")
        for t in uniq:
            print(f"  - {t}")

        browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
