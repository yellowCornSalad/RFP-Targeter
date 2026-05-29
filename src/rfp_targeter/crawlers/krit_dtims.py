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
        """DTiMS 실제 row 구조 (헤더 NO 컬럼은 빠져있음, 7 cells):
        [0] 공고현황 (마감/접수중)
        [1] 공고번호 (YY-NNN)
        [2] 공고명 ← 텍스트만 (a 태그 없음)
        [3] 접수일 ("접수일 YYYY/MM/DD")
        [4] 마감일 ("마감일 YYYY/MM/DD")
        [5] D-day
        [6] 결과 — "보기" 링크 (vpsFileView.do?attcIden=...)
        """
        cells = tr.find_all("td")
        if len(cells) < 7:
            return None

        # 공고명 — idx=2 셀의 텍스트
        title = cells[2].get_text(" ", strip=True)
        if not title or title in ("등록된 정보가 없습니다.", "-"):
            return None

        # 상세 URL — 마지막 셀(결과 "보기")의 링크
        detail_url = None
        result_link = cells[-1].find("a", href=True)
        if result_link:
            href = result_link.get("href", "")
            if href and not href.startswith("javascript:"):
                detail_url = urljoin(LIST_URL, href)

        # 공고번호 — idx=1
        notice_no = cells[1].get_text(strip=True)

        # 접수일/마감일 — "접수일 YYYY/MM/DD" 형식 (prefix 무시하고 정규식)
        def _parse_date(text: str) -> str | None:
            m = re.search(r"(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})", text)
            if m:
                return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
            return None

        posted_at = _parse_date(cells[3].get_text(strip=True))
        deadline_at = _parse_date(cells[4].get_text(strip=True))

        # external_id 우선: 공고번호. fallback: href attcIden, 최후 제목 hash
        external_id = notice_no if re.fullmatch(r"\d{2}-\d{3,4}", notice_no or "") else None
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

        # 사업비·기간 (공통 유틸)
        from rfp_targeter.attachments.budget_extract import extract_budget_mw, extract_duration_months
        mw = extract_budget_mw(body)
        if mw is not None:
            a.budget_mw = mw
        dm2 = extract_duration_months(body)
        if dm2 is not None:
            a.duration_months = dm2
        return a
