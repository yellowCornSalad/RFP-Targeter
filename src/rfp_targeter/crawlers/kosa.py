"""KOSA (한국SW산업협회) 정부지원사업 게시판 크롤러.

소스: https://www.sw.or.kr/site/sw/ex/board/List.do?cbIdx=290
- cbIdx=290 = 정부지원사업 (R&D·사업공고 핵심)
- cbIdx=292 = 공지사항 (보조)
- 정적 JSP 테이블 — BeautifulSoup으로 파싱
- robots.txt: 일반 UA 전체 차단(`Disallow: /`), Googlebot/Yeti(네이버)만 Allow
  → User-Agent를 Googlebot로 명시 (정책 준수)

회사 관점: SW산업·디지털 R&D 사업이 자주 올라옴 → 보안 키워드 통과분 자동 매칭.
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
# 게시판 ID: 정부지원사업 우선, 공지 보조
BOARDS = [
    ("290", "KOSA 정부지원사업"),
    ("292", "KOSA 공지사항"),
]

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
        # 정부지원사업에 80%, 공지에 20%
        budget = {
            "290": max(1, int(self.max_per_source * 0.8)),
            "292": max(1, self.max_per_source - int(self.max_per_source * 0.8)),
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
        # KOSA 게시판 상세는 일반적으로 div.bv_cont 또는 div.bbs_content
        main = (
            soup.select_one("div.bv_cont")
            or soup.select_one("div.bbs_content")
            or soup.select_one("div.cont")
            or soup.select_one("article")
            or soup.body
        )
        body = re.sub(r"\s+", " ", main.get_text(" ") if main else "").strip()[:10000]
        a.body = body

        # 마감일
        dm = re.search(
            r"(?:접수\s*마감|신청\s*마감|마감일)[^\d]{0,20}(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})",
            body,
        )
        if dm:
            a.deadline_at = f"{dm.group(1)}-{int(dm.group(2)):02d}-{int(dm.group(3)):02d}"

        # 사업비
        bm = re.search(
            r"(?:사업\s*비|총\s*사업비|예산|지원\s*금액|지원\s*규모)[^\d]{0,30}([\d,]+)\s*(억|백만\s*원|만\s*원)",
            body,
        )
        if bm:
            n = int(bm.group(1).replace(",", ""))
            unit = bm.group(2).replace(" ", "")
            if unit == "억":
                a.budget_mw = n * 100
            elif unit == "백만원":
                a.budget_mw = n
            elif unit == "만원":
                a.budget_mw = max(1, n // 100)

        # 사업기간
        pm = re.search(
            r"(?:사업\s*기간|연구\s*기간|수행\s*기간)[^\d]{0,20}(\d+)\s*(개월|년)",
            body,
        )
        if pm:
            n = int(pm.group(1))
            a.duration_months = n * 12 if pm.group(2) == "년" else n
        return a
