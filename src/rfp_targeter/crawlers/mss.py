"""중소벤처기업부(MSS) 사업공고 크롤러 — data.go.kr 공식 API.

데이터 소스: 중소벤처기업부_사업공고 (data.go.kr 15113297)
  Endpoint: https://apis.data.go.kr/1421000/mssBizService_v2/getbizList_v2
  데이터 포맷: XML
  일일 트래픽: 100

회사 = 중소기업이라 중기부 R&D·자금·해외진출·인력 사업 모두 직접 매칭 가능.
"""
from __future__ import annotations

import logging
import re as _re
from typing import Iterator
from urllib.parse import unquote, urlencode

from pathlib import Path

from rfp_targeter.attachments import classify, download_file, extract_text, priority
from rfp_targeter.config import secrets
from rfp_targeter.crawlers.base import BaseCrawler
from rfp_targeter.db.models import Announcement

log = logging.getLogger(__name__)

DEFAULT_ENDPOINT = "https://apis.data.go.kr/1421000/mssBizService_v2/getbizList_v2"

# 응답 필드명 (data.go.kr 15113297 실응답 검증, 2026-05-21)
# 핵심: itemId / title / applicationStartDate / applicationEndDate / dataContents
# 담당자/직위는 writerName/writerPosition (agency 아님, mss 자체가 발주처)
_FIELD_MAP = {
    "external_id": ["itemId", "pblancId", "bsnsAncmSeq", "ancmId", "seqNo", "id"],
    "title":       ["title", "pblancNm", "subject", "bsnsAncmNm"],
    "agency":      ["jrsdInstNm", "instNm", "deptName", "agency"],
    "posted_at":   ["applicationStartDate", "pblancBgngYmd", "regDt", "pressDt"],
    "deadline_at": ["applicationEndDate", "pblancEndYmd", "rcptEndYmd", "endDate"],
    "url":         ["pblancUrl", "viewUrl", "detailUrl", "url"],
    "summary":     ["dataContents", "pblancCn", "bsnsAncmCn", "summary"],
    "department":  ["writerPosition", "chrgDeptNm", "deptName"],
    "manager":     ["writerName", "managerName"],
}


def _pick(item: dict, candidates: list[str]) -> str | None:
    for k in candidates:
        v = item.get(k)
        if v not in (None, "", "null"):
            return str(v)
    return None


class MSSCrawler(BaseCrawler):
    source = "mss"
    display_name = "중소벤처기업부 사업공고"

    def __init__(self, base_url: str | None = None) -> None:
        super().__init__(base_url)
        sec = secrets().get("mss", {})
        self.service_key = sec.get("service_key")
        self.endpoint = sec.get("endpoint", DEFAULT_ENDPOINT)

    def list_announcements(self) -> Iterator[Announcement]:
        if not self.service_key or self.service_key == "???":
            log.warning(
                "MSS: data.go.kr serviceKey 미설정 (secrets.yaml 의 mss 섹션). "
                "발급: https://www.data.go.kr/data/15113297/openapi.do"
            )
            return

        # 일일 한도 100 — 보수적으로 페이지당 10건씩
        rows_per_page = 10
        max_pages = max(1, (self.max_per_source + rows_per_page - 1) // rows_per_page)
        seen = 0

        for page in range(1, max_pages + 1):
            sk = unquote(self.service_key)
            params = {
                "serviceKey": sk,
                "pageNo": page,
                "numOfRows": rows_per_page,
            }
            url = f"{self.endpoint}?{urlencode(params)}"
            try:
                r = self.fetch(url)
            except Exception as e:
                log.warning("mss API page %d fail: %s", page, e)
                break

            items = self._extract_items_from_xml(r.text)
            if not items:
                log.info("mss: 항목 없음 (page %d). 응답 첫 300자: %s", page, r.text[:300])
                break

            for item in items:
                a = self._to_announcement(item)
                if a is None:
                    continue
                yield a
                seen += 1
                if seen >= self.max_per_source:
                    return

    def _extract_items_from_xml(self, text: str) -> list[dict]:
        try:
            from xml.etree import ElementTree as ET
            root = ET.fromstring(text)
            items: list[dict] = []
            for item in root.iter("item"):
                d: dict = {}
                file_list = []
                for child in item:
                    if child.tag == "files":
                        for f in child.iter("file"):
                            fname = (f.findtext("fileName") or "").strip()
                            furl = (f.findtext("fileUrl") or "").strip()
                            if fname and furl:
                                file_list.append({"name": fname, "url": furl})
                    else:
                        d[child.tag] = (child.text or "").strip()
                if file_list:
                    d["_files"] = file_list
                items.append(d)
            return items
        except Exception as e:
            log.debug("mss xml parse fail: %s", e)
            return []

    def _to_announcement(self, item: dict) -> Announcement | None:
        import re as _re
        title = _pick(item, _FIELD_MAP["title"])
        url = _pick(item, _FIELD_MAP["url"]) or ""
        external_id = _pick(item, _FIELD_MAP["external_id"])

        # external_id 폴백: URL 안의 pblancId 또는 ID 추출
        if not external_id and url:
            m = _re.search(r"(?:pblancId|nttSeqNo|bbsSeqNo|bcIdx)=([\w_-]+)", url)
            if m:
                external_id = m.group(1)

        if not external_id or not title:
            return None

        # URL 없으면 mss 본 사이트 게시판 패턴으로 구성 (itemId = bcIdx)
        if not url:
            url = f"https://www.mss.go.kr/site/smba/ex/bbs/View.do?cbIdx=86&bcIdx={external_id}"

        dept = _pick(item, _FIELD_MAP["department"]) or ""
        mgr = _pick(item, _FIELD_MAP["manager"]) or ""
        contact_line = " · ".join(filter(None, [dept, mgr]))

        attachments = []
        for f in item.get("_files", []):
            attachments.append({
                "name": f["name"], "url": f["url"], "local_path": None,
                "category": classify(f["name"]),
            })

        return Announcement(
            source=self.source,
            external_id=external_id,
            title=title,
            url=url,
            agency=_pick(item, _FIELD_MAP["agency"]) or "중소벤처기업부",
            posted_at=_pick(item, _FIELD_MAP["posted_at"]),
            deadline_at=_pick(item, _FIELD_MAP["deadline_at"]),
            summary=_pick(item, _FIELD_MAP["summary"]) or contact_line or None,
            body=f"{title}\n{contact_line}",
            attachments=attachments,
        )

    def fetch_detail(self, a: Announcement) -> Announcement:
        """첨부 분류 기반 우선순위 다운로드 (IITP 어댑터 동일 로직).

        API에서 _files가 비어 오는 경우가 많으므로, 본문 페이지(HTML)에서
        '내려받기' 링크를 직접 파싱해 attachments에 추가.
        """
        # API에 첨부가 없으면 본문 페이지에서 직접 추출
        if not a.attachments:
            a.attachments = self._scrape_attachments_from_detail(a.url)

        if not a.attachments:
            return a

        def _ext_pri(name: str) -> int:
            n = (name or "").lower()
            if n.endswith(".hwpx"): return 0
            if n.endswith(".pdf"):  return 1
            if n.endswith(".odt"):  return 2
            if n.endswith(".docx"): return 3
            if n.endswith(".hwp"):  return 9
            return 5

        for att in a.attachments:
            if not att.get("category"):
                att["category"] = classify(att.get("name", ""))
        sorted_atts = sorted(
            a.attachments,
            key=lambda x: (priority(x.get("category", "other")), _ext_pri(x.get("name", ""))),
        )

        text = ""
        for att in sorted_atts:
            cat = att.get("category", "other")
            if cat not in ("notice", "form"):
                continue
            url = att.get("url")
            name = att.get("name") or "attachment.bin"
            if not url:
                continue
            path = download_file(url, a.external_id, name)
            if path is None:
                continue
            att["local_path"] = str(path)
            t = extract_text(path)
            if t and (not text or cat == "notice"):
                text = t
                if cat == "notice":
                    break

        if not text:
            return a

        a.body = (a.body or "") + "\n\n[첨부 본문]\n" + text

        from rfp_targeter.attachments.budget_extract import extract_budget_mw, extract_duration_months
        mw = extract_budget_mw(text)
        if mw is not None:
            a.budget_mw = mw
        dm = extract_duration_months(text)
        if dm is not None:
            a.duration_months = dm
        return a

    def _scrape_attachments_from_detail(self, url: str) -> list[dict]:
        """MSS 본문 페이지(HTML)에서 첨부 직접 파싱.

        패턴 (예: cbIdx=310 사업공고 게시판):
            <td class="file_list">
              <ul>
                <li>
                  <div class="info"><span class="name">파일명.hwpx [크기]</span></div>
                  <div class="link"><a href="/common/board/Download.do?bcIdx=X&cbIdx=Y&streFileNm=UUID.ext">내려받기</a></div>
                </li>
              </ul>
            </td>
        """
        if not url or not url.startswith(("http://", "https://")):
            return []
        try:
            r = self.fetch(url)
        except Exception:
            return []
        from bs4 import BeautifulSoup as _BS
        soup = _BS(r.text, "lxml")
        attachments: list[dict] = []
        for li in soup.select(".file_list li, td.file_list li"):
            name_el = li.select_one(".name")
            if not name_el:
                continue
            name = name_el.get_text(" ", strip=True)
            # 크기 부분 제거 "[111.34 KB]"
            name = _re.sub(r"\s*\[[\d.,]+\s*[KMG]?B\]\s*$", "", name).strip()
            if not name:
                continue
            # 인접 내려받기 링크
            dl = li.select_one("a[href*='Download.do']")
            if not dl:
                continue
            href = dl.get("href", "")
            if not href:
                continue
            full_url = href if href.startswith("http") else f"https://www.mss.go.kr{href}"
            attachments.append({
                "name": name,
                "url": full_url,
                "category": classify(name),
                "local_path": None,
            })
        return attachments
