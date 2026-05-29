"""KRIT PMS Nexacro SPA 의 카드 DOM 구조 + 페이지네이션 탐색.

1차: 카드 selector 확인 (.portal_div_project) → 발견
2차: 모든 페이지 카드 수집 방식 결정 (next 버튼 vs 탭 전환)
"""
from __future__ import annotations

import sys
from playwright.sync_api import sync_playwright

URL = "https://pms.krit.re.kr/kritpmsi/nxui/kritpms/index.jsp"


def extract_cards(page) -> list[dict]:
    """현재 보이는 카드의 정보 추출 (제목/카테고리/마감일/D-day)."""
    return page.evaluate("""
    () => {
        const cards = document.querySelectorAll(".portal_div_project");
        const results = [];
        for (const card of cards) {
            const title = card.querySelector(".portal_sta_projTitle");
            const cat = card.querySelector(".portal_sta_projCore");
            const date = card.querySelector(".portal_sta_projDate");
            const dday = card.querySelector(".portal_sta_projDday");
            // 카드 안에 카드 분류 (공고진행/접수예정) 배지도 있을 수 있음
            const allStatic = card.querySelectorAll(".Static");
            const allTexts = [];
            for (const s of allStatic) {
                const t = (s.innerText || "").trim();
                if (t && t.length < 50) allTexts.push(t);
            }
            results.push({
                title: title ? title.innerText.trim() : null,
                category: cat ? cat.innerText.trim() : null,
                date: date ? date.innerText.trim() : null,
                dday: dday ? dday.innerText.trim() : null,
                all_texts: allTexts,
                cardId: card.id,
            });
        }
        return results;
    }
    """)


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch()  # 기본값 사용 — capture_dashboard.py 와 동일 방식
        page = browser.new_page(
            viewport={"width": 1280, "height": 900},
            locale="ko-KR",
        )
        page.goto(URL, wait_until="domcontentloaded")
        page.wait_for_timeout(5000)  # Nexacro init

        # === 1. 첫 페이지 카드 수집 ===
        cards = extract_cards(page)
        print(f"=== Page 1 — {len(cards)} cards ===")
        for c in cards:
            print(f"  [{c['cardId'][-30:]}]")
            print(f"    cat: {c['category']}")
            print(f"    title: {c['title']}")
            print(f"    date: {c['date']}")
            print(f"    dday: {c['dday']}")
            print(f"    all_texts: {c['all_texts']}")
            print()

        # === 2. 페이지네이션: 다음 화살표 찾기 ===
        # "01 / 05" 같은 표기 → next 버튼 (▶) selector 찾기
        nav_info = page.evaluate("""
        () => {
            const all = document.querySelectorAll("*");
            const results = [];
            for (const el of all) {
                const text = (el.innerText || "").trim();
                if (text === "01 / 05" || /^\\d{2}\\s*\\/\\s*\\d{2}$/.test(text)) {
                    results.push({
                        tag: el.tagName,
                        id: el.id || null,
                        cls: el.className || null,
                        text: text,
                        parent_id: el.parentElement ? el.parentElement.id : null,
                    });
                }
            }
            // 또 ">" 또는 "▶" 단독 텍스트 div
            for (const el of all) {
                const text = (el.innerText || "").trim();
                if ((text === "▶" || text === ">" || text === "▷") && el.tagName === "DIV") {
                    results.push({
                        tag: el.tagName,
                        id: el.id || null,
                        cls: el.className || null,
                        text: "ARROW: " + text,
                    });
                }
            }
            return results.slice(0, 10);
        }
        """)
        print(f"=== Pagination candidates ({len(nav_info)}) ===")
        for n in nav_info:
            print(f"  <{n['tag']} id={n.get('id')} cls={n.get('cls')}>: {n['text']}")

        # === 3. 전체 카드 (모든 페이지) 수집 가능한지 확인 — Nexacro grid 가 dataset 보유 ===
        all_cards_info = page.evaluate("""
        () => {
            // div000, div001, div002, ... 모두 찾기
            const allDivs = document.querySelectorAll("[id*='Tabpage1.form.div0']");
            const ids = [];
            for (const d of allDivs) {
                if (d.id.match(/Tabpage1\\.form\\.div\\d{3}$/)) {
                    ids.push(d.id.match(/div\\d{3}$/)[0]);
                }
            }
            return {total_card_divs: ids.length, sample_ids: ids.slice(0, 25)};
        }
        """)
        print(f"\n=== Total card containers ===")
        print(f"  count: {all_cards_info['total_card_divs']}")
        print(f"  sample ids: {all_cards_info['sample_ids']}")

        browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
