"""KISA (한국인터넷진흥원) 입찰공고 + 위탁과제 크롤러.

- /403 입찰공고 (활발, 1700건+) — 메인 채널
- /408 위탁과제 (보조)

상세: https://www.kisa.or.kr/{board}/form?postSeq=NNN&page=1

회사 본업과 가장 직접 매칭되는 소스 — 보안 기관이 발주.
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

# 게시판 ID → (표시명, 활발도). 활발한 채널부터 순회
BOARDS = [
    ("403", "KISA 입찰공고"),
    ("408", "KISA 위탁과제"),
]


class KISACrawler(BaseCrawler):
    source = "kisa"
    display_name = "KISA"

    def list_announcements(self) -> Iterator[Announcement]:
        rows_per_page = 10
        # 입찰공고에 max_per_source의 80% 할당, 위탁과제에 나머지
        budget = {
            "403": max(1, int(self.max_per_source * 0.8)),
            "408": max(1, self.max_per_source - int(self.max_per_source * 0.8)),
        }

        for board_id, label in BOARDS:
            limit = budget[board_id]
            max_pages = max(1, (limit + rows_per_page - 1) // rows_per_page)
            seen = 0
            for page in range(1, max_pages + 1):
                url = f"{self.base_url}/{board_id}?page={page}"
                try:
                    r = self.fetch(url)
                except Exception as e:
                    log.warning("kisa [%s] page %d fetch fail: %s", board_id, page, e)
                    break

                soup = BeautifulSoup(r.text, "lxml")
                rows = soup.select("table tbody tr")
                if not rows:
                    log.info("kisa [%s]: 더 이상 행 없음 (page %d)", board_id, page)
                    break

                for tr in rows:
                    a = self._parse_row(tr, board_id, label)
                    if a is None:
                        continue
                    yield a
                    seen += 1
                    if seen >= limit:
                        break
                if seen >= limit:
                    break
            log.info("kisa [%s/%s]: %d건 수집", board_id, label, seen)

    def _parse_row(self, tr, board_id: str, label: str) -> Announcement | None:
        link_tag = tr.find("a", href=re.compile(r"postSeq="))
        if link_tag is None:
            return None
        href = link_tag.get("href", "")
        m = re.search(r"postSeq=(\d+)", href)
        if not m:
            return None
        # 게시판이 다르면 같은 postSeq라도 다른 공고 — 충돌 방지 위해 board prefix
        external_id = f"{board_id}-{m.group(1)}"
        title = link_tag.get_text(" ", strip=True)
        if not title:
            return None
        detail_url = urljoin(self.base_url, href) if href.startswith("/") else href

        # 등록일 — 셀에서 YYYY-MM-DD 패턴 찾기
        cells = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
        posted = next((c for c in cells if re.fullmatch(r"\d{4}-\d{2}-\d{2}", c)), None)

        return Announcement(
            source=self.source,
            external_id=external_id,
            title=title,
            url=detail_url,
            agency=label,  # "KISA 입찰공고" or "KISA 위탁과제" 로 발주처 표시
            posted_at=posted,
            summary=None,
        )

    def fetch_detail(self, a: Announcement) -> Announcement:
        # ⚠️ KISA 입찰공고(board 403)는 반드시 첨부 있음.
        # 첨부 0건 추출되면 일시적 fetch 실패 가능성 → 최대 2회 재시도.
        is_bid = a.external_id.startswith("403-")
        max_attempts = 2 if is_bid else 1
        r = None
        for attempt in range(max_attempts):
            try:
                r = self.fetch(a.url)
                break
            except Exception as e:
                if attempt < max_attempts - 1:
                    import time as _time
                    _time.sleep(1.5)  # 재시도 전 대기
                    continue
                log.debug("kisa detail fetch fail %s: %s", a.external_id, e)
                return a
        if r is None:
            return a

        soup = BeautifulSoup(r.text, "lxml")
        for tag in soup(["script", "style", "noscript", "header", "footer", "nav"]):
            tag.decompose()
        main = soup.select_one("div.cont") or soup.select_one("article") or soup.body
        body = re.sub(r"\s+", " ", main.get_text(" ") if main else "").strip()[:10000]
        a.body = body

        # 첨부파일 추출 — board 403은 첨부 0이면 한번 더 fetch + 재시도
        attachments = self._extract_attachments(soup, a.external_id)
        if not attachments and is_bid and max_attempts > 1:
            try:
                import time as _time
                _time.sleep(1.0)
                r2 = self.fetch(a.url)
                soup2 = BeautifulSoup(r2.text, "lxml")
                attachments = self._extract_attachments(soup2, a.external_id)
                log.info("kisa [%s] 첨부 재시도 → %d건", a.external_id, len(attachments))
            except Exception:
                pass
        if attachments:
            a.attachments = attachments

        # 마감일 추출 (KISA 위탁과제는 신청 마감일 표기)
        dm = re.search(r"(?:접수\s*마감|신청\s*마감|마감일)[^\d]{0,20}(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})", body)
        if dm:
            a.deadline_at = f"{dm.group(1)}-{int(dm.group(2)):02d}-{int(dm.group(3)):02d}"

        # 사업비·기간 추출 (공통 유틸 — 소수점·다양한 prefix 지원)
        from rfp_targeter.attachments.budget_extract import extract_budget_mw, extract_duration_months
        mw = extract_budget_mw(body)
        if mw is not None:
            a.budget_mw = mw
        dm2 = extract_duration_months(body)
        if dm2 is not None:
            a.duration_months = dm2
        return a

    def _extract_attachments(self, soup, external_id: str) -> list[dict]:
        """KISA 첨부파일 추출.

        HTML:
            <a href="#fnPostAttachDownload"
               onclick="fnPostAttachDownload(403, '10684', 1, 'KO');"
               title="첨부파일 다운로드">파일명.hwpx (94KB)</a>

        실제 다운로드 (common.js 의 함수 정의 기반):
            GET /post/fileDownload?menuSeq=403&postSeq=10684&attachSeq=1&lang_type=KO
        """
        attachments: list[dict] = []
        # board_detail_attach 영역의 a[href='#fnPostAttachDownload']
        for atag in soup.select("a[href='#fnPostAttachDownload']"):
            onclick = atag.get("onclick", "")
            m = re.search(
                r"fnPostAttachDownload\(\s*(\d+)\s*,\s*['\"]?(\d+)['\"]?\s*,"
                r"\s*(\d+)\s*,\s*['\"]([A-Z]{2})['\"]\s*\)",
                onclick,
            )
            if not m:
                continue
            menu_seq, post_seq, attach_seq, lang_type = m.groups()
            name = atag.get_text(" ", strip=True)
            if not name:
                continue
            url = (
                f"https://www.kisa.or.kr/post/fileDownload"
                f"?menuSeq={menu_seq}&postSeq={post_seq}"
                f"&attachSeq={attach_seq}&lang_type={lang_type}"
            )
            # 카테고리 추정: 파일명에 "공고", "제안요청서", "양식" 등 키워드
            lower_name = name.lower()
            if any(k in name for k in ("공고서", "공고문", "[공고", "입찰공고")):
                cat = "notice"
            elif any(k in name for k in ("제안요청서", "RFP", "요청서")):
                cat = "notice"
            elif any(k in name for k in ("양식", "서식", "신청서", "동의서", "이력서")):
                cat = "form"
            elif any(k in name for k in ("평가", "심사", "기준")):
                cat = "eval"
            else:
                cat = "reference"
            attachments.append({
                "name": name,
                "url": url,
                "category": cat,
                "local_path": None,  # KISA는 대용량 다운 안 함 (링크만)
            })
        if attachments:
            log.debug("kisa [%s] 첨부 %d건 파싱", external_id, len(attachments))
        return attachments
