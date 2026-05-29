"""KRIT (국방기술진흥연구소) 과제관리시스템 PMS 크롤러.

소스: pms.krit.re.kr 의 Nexacro SPA 홈 캐러셀.

배경 (2026-05-29):
- 이전 어댑터는 dtims.krit.re.kr/vps/OINF_CtPrjNotiList.do (정적 HTML 게시판)
- dtims 사이트는 2024년 1월 이후 갱신 정지 — 모든 공번이 24-XXX
- 현재 활성 공고는 pms.krit.re.kr (Nexacro SPA) 에 게재
- pms 는 Nexacro 자체 transaction 프로토콜 사용 → 일반 HTTP 크롤링 불가
- Playwright headless 로 SPA 실행 후 DOM 추출 방식 채택

DOM 구조 (probe 결과):
  .portal_div_project              ← 카드 컨테이너
    .portal_sta_projCore           ← 카테고리 (핵심기술/방산진흥/전력지원)
    .portal_sta_projTitle.pointer  ← 제목 (클릭 가능)
    .portal_sta_projDate           ← "마감일 YYYY-MM-DD"
    .portal_sta_projDday           ← "D-N"
  추가 Static 텍스트:              ← 공고진행/접수중/접수예정, 과제공고/과제기획

캐러셀 페이지네이션 (probe 확정, 2026-05-29):
  .portal_mtab_next   ← 다음 버튼 (id ...btnMtabNext)
  .portal_mtab_prev   ← 이전 버튼 (id ...btnMtabPrev)
  .portal_mtab_page_S ← 현재 페이지 / .portal_mtab_page ← 전체 페이지 ("01" / "05")
  ※ Nexacro 는 JS element.click() 무시 → page.mouse.click(좌표) 실제 이벤트 필요.
  ※ 현재 5페이지 = 현행 2026 공고 17건 (1~4p 각 4건 + 5p 1건). 묵은 2023 데모 탭은 숨김.

이전 dtims 어댑터는 `krit_dtims.py` 로 백업됨 (참고용, 비활성).
"""
from __future__ import annotations

import logging
import re
from typing import Iterator

from rfp_targeter.crawlers.base import BaseCrawler
from rfp_targeter.db.models import Announcement

log = logging.getLogger(__name__)

LIST_URL = "https://pms.krit.re.kr/kritpmsi/nxui/kritpms/index.jsp"

# Playwright 가 cron 환경에서 안정적으로 작동하려면 chromium 설치 필요.
# crawl.yml 에 `python -m playwright install chromium --with-deps` 단계 추가됨.
PAGE_INIT_WAIT_MS = 5000        # Nexacro init 대기 (XML 로드 + 데이터셋 채우기)
PAGE_TRANSITION_WAIT_MS = 1500  # 캐러셀 next 클릭 후 데이터 갱신 대기
MAX_CAROUSEL_PAGES = 10         # 안전 상한. 실제 종료는 page indicator(cur>=total)로 판단 (현재 5페이지/17건)


# DOM 에서 카드 정보 일괄 추출 — JS 한 번에 실행
_EXTRACT_CARDS_JS = """
() => {
    const cards = document.querySelectorAll(".portal_div_project");
    const results = [];
    for (const card of cards) {
        // 캐러셀에서 현재 보이는 카드만 (display/visibility + 크기 확인)
        // 묵은 2023 데모 탭(Tabpage2~4)은 숨김 처리되어 자연 제외됨.
        const cs = window.getComputedStyle(card);
        if (cs.display === "none" || cs.visibility === "hidden") continue;
        const rect = card.getBoundingClientRect();
        if (rect.width === 0 && rect.height === 0) continue;

        const titleEl = card.querySelector(".portal_sta_projTitle");
        const catEl = card.querySelector(".portal_sta_projCore");
        const dateEl = card.querySelector(".portal_sta_projDate");
        const ddayEl = card.querySelector(".portal_sta_projDday");

        // 카드 안의 모든 Static 텍스트 (공고진행/접수중/과제공고 등 배지)
        const badges = [];
        for (const s of card.querySelectorAll(".Static")) {
            const t = (s.innerText || "").trim();
            if (t && t.length < 20) badges.push(t);
        }

        results.push({
            cardId: card.id || "",
            title: titleEl ? titleEl.innerText.trim() : "",
            category: catEl ? catEl.innerText.trim() : "",
            date: dateEl ? dateEl.innerText.trim() : "",
            dday: ddayEl ? ddayEl.innerText.trim() : "",
            badges: badges,
        });
    }
    return results;
}
"""


class KRITCrawler(BaseCrawler):
    """KRIT PMS 캐러셀 크롤러 — Playwright headless 기반."""

    source = "krit"
    display_name = "KRIT"

    def list_announcements(self) -> Iterator[Announcement]:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            log.error(
                "krit_pms: playwright 미설치 — `pip install playwright && "
                "python -m playwright install chromium --with-deps` 필요"
            )
            return

        seen_titles: set[str] = set()
        seen = 0

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch()
                page = browser.new_page(
                    viewport={"width": 1280, "height": 900},
                    locale="ko-KR",
                )
                page.goto(LIST_URL, wait_until="domcontentloaded")
                page.wait_for_timeout(PAGE_INIT_WAIT_MS)

                # 캐러셀 순회 — page indicator(현재/전체)로 마지막 페이지 자동 감지
                page_idx = 0
                for page_idx in range(MAX_CAROUSEL_PAGES):
                    try:
                        cards = page.evaluate(_EXTRACT_CARDS_JS)
                    except Exception as e:
                        log.warning("krit_pms: page %d evaluate fail: %s", page_idx, e)
                        break

                    for c in cards:
                        title = (c.get("title") or "").strip()
                        if not title or title in seen_titles:
                            continue
                        seen_titles.add(title)

                        a = self._make_announcement(c)
                        if a is None:
                            continue
                        yield a
                        seen += 1
                        if seen >= self.max_per_source:
                            browser.close()
                            log.info("krit_pms: %d건 수집 (max 도달)", seen)
                            return

                    # 마지막 페이지 도달 시 종료 (예: 05 / 05)
                    cur, total = self._read_page_state(page)
                    if cur and total and cur >= total:
                        break
                    # 다음 페이지로 (Nexacro 실제 마우스 클릭)
                    if not self._click_next(page):
                        log.info("krit_pms: 다음 버튼 없음/실패 — page %d 에서 중단", page_idx)
                        break
                    page.wait_for_timeout(PAGE_TRANSITION_WAIT_MS)

                browser.close()
        except Exception as e:
            log.exception("krit_pms: Playwright 실행 실패: %s", e)
            return

        log.info("krit_pms: %d건 수집 (캐러셀 %d페이지 순회)", seen, page_idx + 1)

    # 보이는 캐러셀 next 버튼(.portal_mtab_next)의 중심 좌표 반환
    _NEXT_XY_JS = """
    () => {
        for (const el of document.querySelectorAll(".portal_mtab_next")) {
            const cs = window.getComputedStyle(el);
            if (cs.display === "none" || cs.visibility === "hidden") continue;
            const r = el.getBoundingClientRect();
            if (r.width === 0 && r.height === 0) continue;
            return { x: Math.round((r.left + r.right) / 2), y: Math.round((r.top + r.bottom) / 2) };
        }
        return null;
    }
    """

    # 현재/전체 페이지 숫자 읽기 (예: "01" / "05")
    _PAGE_STATE_JS = """
    () => {
        for (const el of document.querySelectorAll(".portal_mtab_page_S")) {
            const cs = window.getComputedStyle(el);
            if (cs.display === "none" || cs.visibility === "hidden") continue;
            const r = el.getBoundingClientRect();
            if (r.width === 0 && r.height === 0) continue;
            let total = null;
            const p = el.parentElement;
            if (p) { const t = p.querySelector(".portal_mtab_page"); if (t) total = t.innerText.trim(); }
            return { cur: el.innerText.trim(), total: total };
        }
        return null;
    }
    """

    def _click_next(self, page) -> bool:
        """캐러셀 next(▶) 클릭. 성공 시 True.

        Nexacro 는 DOM 의 element.click() 을 무시하므로(자체 이벤트 시스템),
        보이는 .portal_mtab_next 의 화면 좌표로 실제 마우스 이벤트를 발생시킨다.
        (probe 로 확정: portal_btn_arrowR/btnNext 류 아님 → portal_mtab_next)
        """
        try:
            xy = page.evaluate(self._NEXT_XY_JS)
            if not xy:
                return False
            page.mouse.click(xy["x"], xy["y"])
            return True
        except Exception as e:
            log.warning("krit_pms: next click 실패: %s", e)
            return False

    def _read_page_state(self, page) -> tuple[int, int]:
        """캐러셀 현재/전체 페이지 번호 (cur, total). 못 읽으면 (0, 0)."""
        try:
            res = page.evaluate(self._PAGE_STATE_JS)
            if not res:
                return (0, 0)
            cur = int(re.sub(r"\D", "", res.get("cur") or "") or 0)
            total = int(re.sub(r"\D", "", res.get("total") or "") or 0)
            return (cur, total)
        except Exception:
            return (0, 0)

    def _make_announcement(self, card: dict) -> Announcement | None:
        title = (card.get("title") or "").strip()
        if not title:
            return None

        # 마감일 추출 (예: "마감일 2026-05-29")
        deadline_at = None
        date_text = card.get("date") or ""
        m = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", date_text)
        if m:
            deadline_at = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"

        # 카테고리 / 배지 정보를 summary 에 보존
        category = (card.get("category") or "").strip()
        badges = [b for b in (card.get("badges") or []) if b]
        summary_parts = []
        if category:
            summary_parts.append(f"[{category}]")
        # 배지 중 의미 있는 것만 (제목·날짜·D-day 중복 제외)
        for b in badges:
            if b in (title, date_text, card.get("dday", "")):
                continue
            if b.startswith("마감일") or b == category:
                continue
            if b in summary_parts:
                continue
            summary_parts.append(b)
        summary = " · ".join(summary_parts) if summary_parts else None

        # external_id — 제목 해시 (KRIT PMS 는 공고번호 노출 안 함)
        # 안정성: 제목 변경 시 새 external_id 가 되어 신규로 인식됨 (수정 공고는 별도 row)
        external_id = f"krit-pms-{abs(hash(title)) % 10**10}"

        return Announcement(
            source=self.source,
            external_id=external_id,
            title=title,
            url=LIST_URL,  # 상세 페이지는 Nexacro SPA 라 직접 URL 추출 어려움 — 홈으로 fallback
            agency="국방기술진흥연구소",
            posted_at=None,  # PMS 홈 카드엔 게시일 미노출
            deadline_at=deadline_at,
            summary=summary,
        )

    def fetch_detail(self, a: Announcement) -> Announcement:
        """KRIT PMS 는 상세 페이지가 Nexacro popup/form 이라 직접 fetch 불가.
        list 단계의 정보만 사용. 본문 없음 → 보안 필터는 제목만으로 판단.
        """
        return a
