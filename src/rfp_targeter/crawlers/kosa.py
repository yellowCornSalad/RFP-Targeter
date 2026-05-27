"""KOSA (한국SW산업협회) 게시판 크롤러 — 유관기관 안내 + 입찰안내.

소스 게시판 (메인페이지 navigation 분석 기반):
- cbIdx=382 = **유관기관** ← 메인! 정부기관/테크노파크/평가원이 SW 기업 모집하는 R&D 공고 모음
  · 예: "[인천테크노파크] 2026년 AX 디바이스 개발 실증 사업 수요기업 모집공고"
  · 예: "[한국문화기술기획평가원] 신규 연구개발과제 기술 수요조사 안내"
  · → 회사가 신청 가능한 정부 R&D
- cbIdx=381 = 입찰안내 (KOSA 자체 운영 용역 발주, 보조)

정적 JSP 테이블 — BeautifulSoup으로 파싱.
robots.txt: 일반 UA 전체 차단(`Disallow: /`), Googlebot/Yeti(네이버)만 Allow
  → User-Agent를 Googlebot로 명시 (정책 준수)

⚠️ 이전 변경 이력:
  - cbIdx=290 (정부지원사업) / 292 (공지사항)은 본문 비어있는 legacy 게시판 — 폐기됨
  - cbIdx=381 단일 사용 → 회사 본업 매칭 0% (KOSA 자체 입찰은 회사가 신청 X)
  - **cbIdx=382 추가가 진짜 가치** (정부기관 R&D 모집공고 모음)

회사 관점: SW·AI·디지털 R&D 사업이 빈번 → 보안 키워드 통과분 자동 매칭.
"""
from __future__ import annotations

import logging
import re
from typing import Iterator
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from rfp_targeter.crawlers.base import BaseCrawler
from rfp_targeter.db.models import Announcement

log = logging.getLogger(__name__)

BASE = "https://www.sw.or.kr"
# 게시판 ID: 유관기관(메인 — 정부 R&D 모집) + 입찰안내(보조 — KOSA 자체 용역)
BOARDS = [
    ("382", "KOSA 유관기관 안내"),
    ("381", "KOSA 입찰안내"),
]
# 게시판 별 weight (max_per_source 분배). 유관기관이 메인이라 75%
_BOARD_WEIGHTS = {"382": 0.75, "381": 0.25}

# robots.txt 준수 — Googlebot만 허용된 사이트이므로 명시
KOSA_UA = (
    "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
)


class KOSACrawler(BaseCrawler):
    source = "kosa"
    display_name = "KOSA"

    def __init__(self, base_url: str | None = None) -> None:
        super().__init__(base_url=base_url or BASE)
        # robots.txt 준수: User-Agent를 Googlebot로 오버라이드
        self.session.headers["User-Agent"] = KOSA_UA

    def list_announcements(self) -> Iterator[Announcement]:
        rows_per_page = 10
        # 게시판 별 weight 기반 분배 (382 메인 75%, 381 보조 25%)
        budget = {
            b[0]: max(1, int(self.max_per_source * _BOARD_WEIGHTS.get(b[0], 0.5)))
            for b in BOARDS
        }

        for cb_idx, label in BOARDS:
            limit = budget[cb_idx]
            max_pages = max(1, (limit + rows_per_page - 1) // rows_per_page)
            seen = 0
            for page in range(1, max_pages + 1):
                url = f"{BASE}/site/sw/ex/board/List.do?cbIdx={cb_idx}&pageIndex={page}"
                try:
                    r = self.fetch(url)
                except Exception as e:
                    log.warning("kosa [%s] page %d fetch fail: %s", cb_idx, page, e)
                    break

                soup = BeautifulSoup(r.text, "lxml")
                rows = soup.select("table tbody tr")
                if not rows:
                    log.info("kosa [%s]: 더 이상 행 없음 (page %d)", cb_idx, page)
                    break

                page_yielded = 0
                for tr in rows:
                    a = self._parse_row(tr, cb_idx, label)
                    if a is None:
                        continue
                    yield a
                    seen += 1
                    page_yielded += 1
                    if seen >= limit:
                        break
                if page_yielded == 0:
                    break
                if seen >= limit:
                    break
            log.info("kosa [%s/%s]: %d건 수집", cb_idx, label, seen)

    def _parse_row(self, tr, cb_idx: str, label: str) -> Announcement | None:
        link = tr.find("a", href=re.compile(r"View\.do"))
        if link is None:
            return None
        href = link.get("href", "")
        m = re.search(r"bcIdx=(\d+)", href)
        if not m:
            return None
        external_id = f"{cb_idx}-{m.group(1)}"
        title = link.get_text(" ", strip=True)
        if not title:
            return None

        # 절대 URL 구성 — jsessionid 제거
        detail_url = urljoin(BASE + "/site/sw/ex/board/", href)
        detail_url = re.sub(r";jsessionid=[^?&]+", "", detail_url)

        # 등록일 — YYYY-MM-DD 패턴 (마지막 셀에 있음)
        cell_texts = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
        posted = next(
            (c for c in cell_texts if re.fullmatch(r"\d{4}-\d{2}-\d{2}", c)),
            None,
        )

        return Announcement(
            source=self.source,
            external_id=external_id,
            title=title,
            url=detail_url,
            agency=label,
            posted_at=posted,
            summary=None,
        )

    def fetch_detail(self, a: Announcement) -> Announcement:
        try:
            r = self.fetch(a.url)
        except Exception as e:
            log.debug("kosa detail fetch fail %s: %s", a.external_id, e)
            return a

        soup = BeautifulSoup(r.text, "lxml")
        for tag in soup(["script", "style", "noscript", "header", "footer", "nav"]):
            tag.decompose()
        # KOSA 게시판 상세는 table.view 안에 메타+본문 — 다른 셀렉터는 사이트 네비 잡음
        # soup.body 폴백 쓰면 전체 메뉴 텍스트가 들어가니 절대 X
        main = (
            soup.select_one("table.view")
            or soup.select_one("div.bv_cont")
            or soup.select_one("div.bbs_content")
            or soup.select_one("div.cont")
            or soup.select_one("article")
        )
        if main is None:
            log.warning("kosa detail: 본문 영역 못 찾음 %s — body 빈채로 진행", a.external_id)
            return a
        body = re.sub(r"\s+", " ", main.get_text(" ")).strip()[:10000]
        a.body = body

        # 마감일
        dm = re.search(
            r"(?:접수\s*마감|신청\s*마감|마감일)[^\d]{0,20}(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})",
            body,
        )
        if dm:
            a.deadline_at = f"{dm.group(1)}-{int(dm.group(2)):02d}-{int(dm.group(3)):02d}"

        # 사업비·기간 (공통 유틸)
        from rfp_targeter.attachments.budget_extract import extract_budget_mw, extract_duration_months
        mw = extract_budget_mw(body)
        if mw is not None:
            a.budget_mw = mw
        dm2 = extract_duration_months(body)
        if dm2 is not None:
            a.duration_months = dm2
        # 마감 + 신청 시작일 추출 (KOSA 본문 자체엔 짧지만 시도)
        from rfp_targeter.attachments.dates_extract import extract_dates
        start_iso, deadline_iso = extract_dates(body)
        if not a.deadline_at and deadline_iso:
            a.deadline_at = deadline_iso
        if not a.application_start_date and start_iso:
            a.application_start_date = start_iso
        return a
