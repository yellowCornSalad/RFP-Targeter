"""IITP (정보통신기획평가원) 사업공고 크롤러 — data.go.kr 공식 API 사용.

⚠️ IITP 본 사이트(iitp.kr)는 robots.txt 가 전체 크롤링을 금지함 (`Disallow: /`).
따라서 직접 크롤링은 부적절. 대신 공공데이터포털의 공식 API를 사용.

데이터 소스: 과학기술정보통신부 사업공고
  https://www.data.go.kr/data/15074634/openapi.do
  - REST GET, serviceKey 인증, XML/JSON 응답
  - IITP 포함 과기정통부 산하 모든 R&D 공고 통합
  - 일 1회 갱신

사용 전:
  1. data.go.kr 회원가입 + 위 API 활용신청 (즉시 자동 승인)
  2. 발급받은 serviceKey를 config/secrets.yaml 에 넣기:
        data_go_kr:
          service_key: "여기에_키_입력"

응답 필드명·엔드포인트가 명세와 다를 수 있어 유연하게 매핑.
처음 한 번 돌릴 때 응답 raw 샘플을 로그로 출력 (DEBUG 레벨) — 검증용.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterator
from urllib.parse import unquote, urlencode

from rfp_targeter.attachments import classify, download_file, extract_text, priority
from rfp_targeter.config import secrets
from rfp_targeter.crawlers.base import BaseCrawler
from rfp_targeter.db.models import Announcement

log = logging.getLogger(__name__)

# 과학기술정보통신부 사업공고 (data.go.kr/data/15074634)
# 정확한 endpoint (활용신청 상세 확인): /1721000/msitannouncementinfo/businessAnnouncMentList
# 주의: 'AnnouncMent' 의 M 이 대문자 (오타 아님)
DEFAULT_ENDPOINT = "https://apis.data.go.kr/1721000/msitannouncementinfo/businessAnnouncMentList"

# 실제 응답 필드명 (data.go.kr 15074634, 검증 2026-05-20)
# response.body.items.item 안의 태그명
_FIELD_MAP = {
    "external_id": ["nttSeqNo", "bsnsAncmSeq", "ancmId", "seqNo", "id"],
    "title": ["subject", "bsnsAncmNm", "title"],
    "agency": ["deptName", "jrsdInstNm", "ministryNm", "instNm", "agency"],
    "posted_at": ["pressDt", "bsnsAncmYmd", "postDate", "regDt"],
    "deadline_at": ["rcptEndYmd", "rcptEndDt", "endDate", "deadline"],
    "url": ["viewUrl", "bsnsAncmDtlUrl", "detailUrl", "url"],
    "summary": ["bsnsAncmCn", "bsnsSumry", "summary", "ancmCn"],
    "department": ["deptName", "chrgDeptNm", "deptNm"],
    "manager": ["managerName", "chrgPsnNm"],
    "manager_tel": ["managerTel", "chrgTelNo"],
}


def _pick(item: dict, candidates: list[str]) -> str | None:
    """응답 dict에서 후보 키 중 첫 번째로 값 있는 것 반환."""
    for k in candidates:
        v = item.get(k)
        if v not in (None, "", "null"):
            return str(v)
    return None


class IITPCrawler(BaseCrawler):
    source = "iitp"
    display_name = "IITP (과기정통부 사업공고 API)"

    def __init__(self, base_url: str | None = None) -> None:
        super().__init__(base_url)
        sec = secrets().get("data_go_kr", {})
        self.service_key = sec.get("service_key")
        self.endpoint = sec.get("endpoint", DEFAULT_ENDPOINT)
        # IITP 만 필터링 (담당부서 또는 사업명 포함어 기준)
        self.iitp_only = sec.get("iitp_only_filter", True)

    def list_announcements(self) -> Iterator[Announcement]:
        if not self.service_key or self.service_key == "???":
            log.warning(
                "IITP: data.go.kr serviceKey 미설정. config/secrets.yaml 확인 필요. "
                "발급: https://www.data.go.kr/data/15074634/openapi.do"
            )
            return

        # API가 numOfRows 지정에도 페이지당 10건만 반환 — 여러 페이지 돌면서 누적
        rows_per_page = 10
        max_pages = max(1, (self.max_per_source + rows_per_page - 1) // rows_per_page)
        seen = 0

        for page in range(1, max_pages + 1):
            # serviceKey 가 이미 URL 인코딩된 'Encoding 키'면 unquote 후 urlencode 해야 이중 인코딩 안 됨
            sk = unquote(self.service_key)
            params = {
                "serviceKey": sk,
                "pageNo": page,
                "numOfRows": rows_per_page,
                "type": "json",   # JSON 우선, 안 되면 XML 폴백 추가
            }
            url = f"{self.endpoint}?{urlencode(params)}"
            try:
                r = self.fetch(url)
            except Exception as e:
                log.warning("iitp API page %d fail: %s", page, e)
                break

            data = self._parse_response(r)
            items = self._extract_items(data)
            if not items:
                # JSON 실패 또는 XML 응답 — 모든 페이지에서 폴백 시도
                items = self._extract_items_from_xml(r.text)
            if not items:
                log.info("iitp: 항목 없음 (page %d). 응답 첫 300자: %s", page, r.text[:300])
                break

            for item in items:
                a = self._to_announcement(item)
                if a is None:
                    continue
                if self.iitp_only and not self._is_iitp(a, item):
                    continue
                yield a
                seen += 1
                if seen >= self.max_per_source:
                    return

    def _parse_response(self, r) -> dict | list:
        """JSON 응답 파싱. 실패 시 빈 dict."""
        try:
            return r.json()
        except Exception:
            return {}

    def _extract_items(self, data) -> list[dict]:
        """공공데이터포털 표준 구조에서 items 추출."""
        if not data:
            return []
        # 표준 경로: response.body.items 또는 response.body.items.item
        try:
            body = data.get("response", {}).get("body", {})
            items = body.get("items")
            if isinstance(items, dict):
                items = items.get("item", [])
            if isinstance(items, dict):
                items = [items]
            return items or []
        except (AttributeError, TypeError):
            return []

    def _extract_items_from_xml(self, text: str) -> list[dict]:
        """XML 응답 파싱 (JSON 미지원 시). files 도 함께 추출."""
        try:
            from xml.etree import ElementTree as ET
            root = ET.fromstring(text)
            items = []
            for item in root.iter("item"):
                d = {}
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
            log.debug("xml parse fail: %s", e)
            return []

    def _to_announcement(self, item: dict) -> Announcement | None:
        import re as _re
        title = _pick(item, _FIELD_MAP["title"])
        url = _pick(item, _FIELD_MAP["url"]) or ""
        external_id = _pick(item, _FIELD_MAP["external_id"])

        # external_id 폴백: viewUrl 안의 nttSeqNo 또는 bbsSeqNo 추출
        if not external_id and url:
            m = _re.search(r"nttSeqNo=(\d+)", url)
            if m:
                external_id = m.group(1)
            else:
                m = _re.search(r"bbsSeqNo=(\d+)", url)
                if m:
                    external_id = m.group(1)

        if not external_id or not title:
            return None

        # summary 없는 응답이 많음 — 담당부서+담당자+연락처를 보조 정보로 합쳐 본문 생성
        dept = _pick(item, _FIELD_MAP["department"]) or ""
        mgr = _pick(item, _FIELD_MAP["manager"]) or ""
        tel = _pick(item, _FIELD_MAP["manager_tel"]) or ""
        contact_line = " · ".join(filter(None, [dept, mgr, tel]))

        # 첨부 파일 메타 (다운로드는 fetch_detail에서, 분류는 즉시)
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
            agency=_pick(item, _FIELD_MAP["agency"]) or "과학기술정보통신부",
            posted_at=_pick(item, _FIELD_MAP["posted_at"]),
            deadline_at=_pick(item, _FIELD_MAP["deadline_at"]),
            summary=_pick(item, _FIELD_MAP["summary"]) or contact_line or None,
            body=f"{title}\n{contact_line}",  # 보안 필터 매칭용 최소 본문 (fetch_detail에서 첨부 텍스트로 보강)
            attachments=attachments,
        )

    def fetch_detail(self, a: Announcement) -> Announcement:
        """첨부 .hwpx/.pdf 1개 다운로드 + 텍스트 추출하여 body 보강.

        - 보안 필터 통과 가능성 있는 (정보보호*, AI, ICT) 공고만 받기는 비효율 — 일단 모두 시도
        - 첫 번째 첨부만 (보통 공고문 자체. 신청서·양식은 텍스트 가치 낮음)
        - 다운로드 실패해도 a 그대로 반환
        """
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

        # 카테고리 미분류 첨부 분류 + 정렬 (카테고리 우선순위 → 확장자 우선순위)
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
            # notice·form 만 다운로드 (eval·reference·other 는 메타만)
            if cat not in ("notice", "form"):
                continue
            url = att.get("url")
            name = att.get("name") or "attachment.bin"
            if not url:
                continue
            path = download_file(url, a.external_id, name, referer="https://www.msit.go.kr/")
            if path is None:
                continue
            att["local_path"] = str(path)
            t = extract_text(path)
            # 본문 텍스트는 notice 우선, 없으면 form
            if t and (not text or cat == "notice"):
                text = t
                if cat == "notice":
                    break

        if not text:
            return a

        # 기존 body(제목·부서) + 첨부 본문 합치기
        a.body = (a.body or "") + "\n\n[첨부 본문]\n" + text

        # 첨부 본문에서 예산·기간 추출
        import re
        bm = re.search(r"(?:총\s*사업비|사업비|예산|총\s*연구비)[^\d]{0,30}([\d,]+)\s*(억|백만\s*원|만\s*원)", text)
        if bm:
            n = int(bm.group(1).replace(",", ""))
            unit = bm.group(2).replace(" ", "")
            if unit == "억":
                a.budget_mw = n * 100
            elif unit == "백만원":
                a.budget_mw = n
            elif unit == "만원":
                a.budget_mw = max(1, n // 100)

        pm = re.search(r"(?:사업\s*기간|연구\s*기간|총\s*연구기간)[^\d]{0,30}(\d+)\s*(개월|년)", text)
        if pm:
            n = int(pm.group(1))
            a.duration_months = n * 12 if pm.group(2) == "년" else n

        dm = re.search(r"(?:접수\s*마감|신청\s*마감|마감일|접수기간[^~]*~)[^\d]{0,20}(\d{4})[.\-/년](\s*)(\d{1,2})[.\-/월](\s*)(\d{1,2})", text)
        if dm:
            a.deadline_at = f"{dm.group(1)}-{int(dm.group(3)):02d}-{int(dm.group(5)):02d}"

        return a

    def _is_iitp(self, a: Announcement, raw: dict) -> bool:
        """IITP가 발주한 공고인지 추정. 담당기관·제목·부서명에 IITP/정보통신기획평가원 포함."""
        keys = " ".join(
            filter(None, [
                a.agency, a.title,
                _pick(raw, _FIELD_MAP["department"]) or "",
            ])
        ).lower()
        return ("iitp" in keys) or ("정보통신기획평가원" in keys)
