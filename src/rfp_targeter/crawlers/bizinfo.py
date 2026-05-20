"""기업마당(bizinfo.go.kr) 사업공고 크롤러.

목록: https://www.bizinfo.go.kr/web/lay1/bbs/S1T122C128/AS/74/list.do?cpage=N&rows=15
상세: /sii/siia/selectSIIA200Detail.do?pblancId=PBLN_000000000122201

컬럼: 번호 / 지원분야 / 사업명(링크) / 신청기간 / 소관부처 / 사업수행기관 / 등록일 / 조회수
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


LIST_PATH = "/web/lay1/bbs/S1T122C128/AS/74/list.do"
DETAIL_PATH = "/sii/siia/selectSIIA200Detail.do"


class BizinfoCrawler(BaseCrawler):
    source = "bizinfo"
    display_name = "기업마당"

    def list_announcements(self) -> Iterator[Announcement]:
        # cpage=1 부터 max_per_source 만큼 가져옴 (페이지당 15건 기본)
        rows_per_page = 15
        max_pages = max(1, (self.max_per_source + rows_per_page - 1) // rows_per_page)
        seen = 0

        for cpage in range(1, max_pages + 1):
            url = f"{self.base_url}{LIST_PATH}?cpage={cpage}&rows={rows_per_page}"
            try:
                r = self.fetch(url)
            except Exception as e:
                log.warning("bizinfo list page %d fetch fail: %s", cpage, e)
                break

            soup = BeautifulSoup(r.text, "lxml")
            rows = soup.select("table tbody tr")
            if not rows:
                log.info("bizinfo: 더 이상 행 없음 (page %d)", cpage)
                break

            for tr in rows:
                a = self._parse_row(tr)
                if a is None:
                    continue
                yield a
                seen += 1
                if seen >= self.max_per_source:
                    return

    def _parse_row(self, tr) -> Announcement | None:
        tds = tr.find_all("td")
        if len(tds) < 6:
            return None

        link_tag = tr.find("a", href=re.compile(r"pblancId="))
        if link_tag is None:
            return None
        href = link_tag.get("href", "")
        m = re.search(r"pblancId=([A-Z_0-9]+)", href)
        if not m:
            return None
        external_id = m.group(1)
        title = link_tag.get_text(strip=True)
        if not title:
            return None
        detail_url = urljoin(self.base_url, href) if href.startswith("/") else href

        # 컬럼 위치는 사이트마다 변동 가능 — 안전하게 텍스트로 매칭
        cells = [td.get_text(" ", strip=True) for td in tds]
        # 일반적 순서: [번호, 지원분야, 사업명, 신청기간, 소관부처, 사업수행기관, 등록일, 조회수]
        period = next((c for c in cells if re.search(r"\d{4}-\d{2}-\d{2}", c) and "~" in c), None)
        agency = None
        posted = None
        for c in cells:
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", c):
                posted = c
            elif agency is None and c and not re.search(r"\d{4}-\d{2}-\d{2}", c) and c != title:
                # 부처 후보 — 길이가 짧고 한글이면
                if 2 <= len(c) <= 30 and re.search(r"[가-힣]", c):
                    agency = c

        deadline_at = None
        if period:
            dm = re.search(r"(\d{4}-\d{2}-\d{2})\s*~\s*(\d{4}-\d{2}-\d{2})", period)
            if dm:
                deadline_at = dm.group(2)

        return Announcement(
            source=self.source,
            external_id=external_id,
            title=title,
            url=detail_url,
            agency=agency,
            posted_at=posted,
            deadline_at=deadline_at,
            summary=None,  # 상세 페이지에서 채움 (fetch_detail)
        )

    def fetch_detail(self, a: Announcement) -> Announcement:
        """상세 페이지에서 본문·예산 정보 추가."""
        try:
            r = self.fetch(a.url)
        except Exception as e:
            log.debug("bizinfo detail fetch fail %s: %s", a.external_id, e)
            return a

        soup = BeautifulSoup(r.text, "lxml")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        # 상세 페이지 본문 — 영역이 명확하지 않으면 전체 텍스트에서 정제
        main = soup.select_one(".view") or soup.select_one("#bbsContent") or soup.body
        body = re.sub(r"\s+", " ", main.get_text(" ") if main else "").strip()[:10000]
        a.body = body

        # 예산 추출 시도
        bm = re.search(r"(?:사업\s*비|지원\s*규모|총\s*사업비|예산)[^\d]{0,30}([\d,]+)\s*(억|백만\s*원|만\s*원|원)", body)
        if bm:
            n = int(bm.group(1).replace(",", ""))
            unit = bm.group(2).replace(" ", "")
            if unit == "억":
                a.budget_mw = n * 100
            elif unit == "백만원":
                a.budget_mw = n
            elif unit == "만원":
                a.budget_mw = max(1, n // 100)
            elif unit == "원":
                a.budget_mw = max(1, n // 1_000_000)
        return a
