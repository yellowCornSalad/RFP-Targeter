"""NIPA (정보통신산업진흥원) 사업공고 크롤러.

소스:
- /home/2-2 사업공고 (R&D·모집사업 핵심)
- /home/2-3 입찰공고 (조달·용역, 보조)

정적 SSR 페이지 — BeautifulSoup으로 파싱 가능.
robots.txt: /home/, /main/ 모두 허용. data.go.kr OpenAPI 없음 → HTML 크롤링이 1차.

회사 관점: SW·AI·정보보안 R&D 발주가 활발 → 중요한 소스.
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

BASE = "https://www.nipa.kr"
# 게시판: (path, key, label, 비중) — key는 selectBbsNttView.do의 key 파라미터
BOARDS = [
    ("/home/2-2", "122", "NIPA 사업공고",  0.75),
    ("/home/2-3", "124", "NIPA 입찰공고",  0.25),
]


class NIPACrawler(BaseCrawler):
    source = "nipa"
    display_name = "NIPA"

    def list_announcements(self) -> Iterator[Announcement]:
        rows_per_page = 10
        for path, key, label, weight in BOARDS:
            limit = max(1, int(self.max_per_source * weight))
            max_pages = max(1, (limit + rows_per_page - 1) // rows_per_page)
            seen = 0
            for page in range(1, max_pages + 1):
                url = f"{BASE}{path}?curPage={page}"
                try:
                    r = self.fetch(url)
                except Exception as e:
                    log.warning("nipa [%s] page %d fetch fail: %s", path, page, e)
                    break

                soup = BeautifulSoup(r.text, "lxml")
                rows = soup.select("table tbody tr")
                if not rows:
                    log.info("nipa [%s]: 더 이상 행 없음 (page %d)", path, page)
                    break

                page_yielded = 0
                for tr in rows:
                    a = self._parse_row(tr, key, label)
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
            log.info("nipa [%s/%s]: %d건 수집", path, label, seen)

    def _parse_row(self, tr, key: str, label: str) -> Announcement | None:
        # 행에서 selectBbsNttView.do 링크 우선, 없으면 첫 a 태그
        link = tr.find("a", href=re.compile(r"selectBbsNttView\.do"))
        if link is None:
            link = tr.find("a", href=True)
        if link is None:
            return None
        href = link.get("href", "")
        if href.startswith("javascript:"):
            return None
        title = link.get_text(" ", strip=True)
        if not title:
            return None

        detail_url = urljoin(BASE, href)
        # nttNo 추출 → external_id
        m = re.search(r"nttNo=(\d+)", detail_url)
        external_id = f"nipa-{key}-{m.group(1)}" if m else f"nipa-{key}-{abs(hash(title)) % 10**10}"

        # 날짜 추출 — 모든 셀에서 YYYY-MM-DD 패턴
        cell_texts = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
        dates = []
        for t in cell_texts:
            for dm in re.finditer(r"(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})", t):
                dates.append(f"{dm.group(1)}-{int(dm.group(2)):02d}-{int(dm.group(3)):02d}")
        posted_at = dates[0] if dates else None

        # D-XX 패턴이 있으면 거기서 마감일 추정 (오늘 + N일)
        # 단순화: 본문에서 더 정확히 추출되도록 list에선 None 유지
        return Announcement(
            source=self.source,
            external_id=external_id,
            title=title,
            url=detail_url,
            agency=label,
            posted_at=posted_at,
            summary=None,
        )

    def fetch_detail(self, a: Announcement) -> Announcement:
        try:
            r = self.fetch(a.url)
        except Exception as e:
            log.debug("nipa detail fetch fail %s: %s", a.external_id, e)
            return a

        soup = BeautifulSoup(r.text, "lxml")
        for tag in soup(["script", "style", "noscript", "header", "footer", "nav"]):
            tag.decompose()
        # NIPA 게시판 상세 본문 — 일반적으로 div.bbs_view 또는 div.viewArea
        main = (
            soup.select_one("div.bbs_view")
            or soup.select_one("div.viewArea")
            or soup.select_one("div.cont")
            or soup.select_one("article")
            or soup.body
        )
        body = re.sub(r"\s+", " ", main.get_text(" ") if main else "").strip()[:10000]
        a.body = body

        # 마감일
        dm = re.search(
            r"(?:접수\s*마감|신청\s*마감|마감일|공모\s*기한)[^\d]{0,20}(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})",
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
        return a
