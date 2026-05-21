"""KRIT (국방기술진흥연구소) 핵심기술 과제공고 크롤러.

소스: DTiMS 열린정보마당 게시판
- 목록: https://dtims.krit.re.kr/vps/OINF_CtPrjNotiList.do?pageIndex={n}
- 정적 JSP 테이블 — BeautifulSoup으로 파싱 가능 (SPA 아님)
- robots.txt: /adm*/만 차단, 게시판 허용 (단 보수적 delay 권장)
- data.go.kr 공식 API 없음 — HTML 크롤링이 유일 경로

회사 관점: 국방 사이버보안 / 군용 AI / 민군겸용 기술 과제가 간헐적으로 올라옴.
직접 매칭은 KISA·IITP보단 약하지만 키워드 보안필터 통과분만 자동 채택.
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

# DTiMS 게시판 (KRIT 메인 도메인이 아닌 서브도메인)
LIST_URL = "https://dtims.krit.re.kr/vps/OINF_CtPrjNotiList.do"


class KRITCrawler(BaseCrawler):
    source = "krit"
    display_name = "KRIT"

    def list_announcements(self) -> Iterator[Announcement]:
        rows_per_page = 10
        max_pages = max(1, (self.max_per_source + rows_per_page - 1) // rows_per_page)
        seen = 0

        for page in range(1, max_pages + 1):
            url = f"{LIST_URL}?pageIndex={page}"
            try:
                r = self.fetch(url)
            except Exception as e:
                log.warning("krit page %d fetch fail: %s", page, e)
                break

            soup = BeautifulSoup(r.text, "lxml")
            # DTiMS는 게시판 tbody tr 패턴. 헤더 분리 안 되어있을 수 있어 fallback
            rows = soup.select("table tbody tr")
            if not rows:
                rows = soup.select("table tr")[1:]  # 첫 행이 헤더일 때
            if not rows:
                log.info("krit: 더 이상 행 없음 (page %d)", page)
                break

            page_yielded = 0
            for tr in rows:
                a = self._parse_row(tr)
                if a is None:
                    continue
                yield a
                seen += 1
                page_yielded += 1
                if seen >= self.max_per_source:
                    break

            if page_yielded == 0:
                # 빈 페이지 = 마지막 페이지 초과
                break
            if seen >= self.max_per_source:
                break

        log.info("krit: %d건 수집", seen)

    def _parse_row(self, tr) -> Announcement | None:
        """DTiMS row 컬럼: NO / 공고현황 / 공고번호 / 공고명 / 접수일 / 마감일 / D-day / 결과."""
        cells = tr.find_all("td")
        if len(cells) < 5:
            return None

        # 공고명 셀 — 보통 4번째(idx 3) 컬럼. 그 안에 a 태그 있으면 상세 URL
        title_cell = None
        title = None
        detail_url = None
        for c in cells:
            link = c.find("a", href=True)
            if link and link.get_text(strip=True):
                title_cell = c
                title = link.get_text(" ", strip=True)
                href = link.get("href", "")
                if href and not href.startswith("javascript:"):
                    detail_url = urljoin(LIST_URL, href)
                break
        if not title:
            return None

        # 공고번호 — title_cell 직전(또는 자체 셀) 텍스트에서 'YY-NNN' 패턴
        cell_texts = [c.get_text(" ", strip=True) for c in cells]
        notice_no = next(
            (t for t in cell_texts if re.fullmatch(r"\d{2}-\d{3,4}", t)),
            None,
        )

        # 접수일/마감일 — YYYY-MM-DD 패턴
        dates = []
        for t in cell_texts:
            m = re.search(r"(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})", t)
            if m:
                dates.append(f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}")
        posted_at = dates[0] if dates else None
        deadline_at = dates[1] if len(dates) >= 2 else None

        # external_id 우선순위: 공고번호 → href에서 attcIden 추출 → 제목 hash
        external_id = notice_no
        if not external_id and detail_url:
            m = re.search(r"(?:attcIden|prjId|notiId)=(\w+)", detail_url)
            if m:
                external_id = m.group(1)
        if not external_id:
            external_id = f"krit-{abs(hash(title)) % 10**10}"

        return Announcement(
            source=self.source,
            external_id=external_id,
            title=title,
            url=detail_url or LIST_URL,
            agency="국방기술진흥연구소 (DTiMS)",
            posted_at=posted_at,
            deadline_at=deadline_at,
            summary=None,
        )

    def fetch_detail(self, a: Announcement) -> Announcement:
        """상세 페이지에서 본문·사업비·기간 보강. 실패 시 그대로 반환."""
        if not a.url or "dtims.krit.re.kr" not in a.url:
            return a
        try:
            r = self.fetch(a.url)
        except Exception as e:
            log.debug("krit detail fetch fail %s: %s", a.external_id, e)
            return a

        soup = BeautifulSoup(r.text, "lxml")
        for tag in soup(["script", "style", "noscript", "header", "footer", "nav"]):
            tag.decompose()
        main = soup.select_one("div.contents") or soup.select_one("article") or soup.body
        body = re.sub(r"\s+", " ", main.get_text(" ") if main else "").strip()[:10000]
        a.body = body

        # 마감일 — list에서 못 잡았으면 본문에서 재시도
        if not a.deadline_at:
            dm = re.search(
                r"(?:접수\s*마감|신청\s*마감|마감일)[^\d]{0,20}(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})",
                body,
            )
            if dm:
                a.deadline_at = f"{dm.group(1)}-{int(dm.group(2)):02d}-{int(dm.group(3)):02d}"

        # 사업비 — '사업비/총사업비/연구비/예산' + 숫자 + (억|백만원|만원)
        bm = re.search(
            r"(?:사업\s*비|총\s*사업비|연구\s*비|예산|지원\s*금액)[^\d]{0,30}([\d,]+)\s*(억|백만\s*원|만\s*원)",
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
