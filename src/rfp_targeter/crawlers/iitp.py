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
from typing import Iterator
from urllib.parse import unquote, urlencode

from rfp_targeter.config import secrets
from rfp_targeter.crawlers.base import BaseCrawler
from rfp_targeter.db.models import Announcement

log = logging.getLogger(__name__)

# 과학기술정보통신부 사업공고 (data.go.kr/data/15074634)
# 정확한 endpoint (활용신청 상세 확인): /1721000/msitannouncementinfo/businessAnnouncMentList
# 주의: 'AnnouncMent' 의 M 이 대문자 (오타 아님)
DEFAULT_ENDPOINT = "https://apis.data.go.kr/1721000/msitannouncementinfo/businessAnnouncMentList"

# 응답 필드명 후보 (공공데이터포털 일반 패턴 + IITP 특화 추측)
# 실제 응답 보고 _FIELD_MAP 수정
_FIELD_MAP = {
    "external_id": ["bsnsAncmSeq", "ancmId", "seqNo", "id"],
    "title": ["bsnsAncmNm", "bsnsAncmTitle", "title", "ancmTitle"],
    "agency": ["jrsdInstNm", "ministryNm", "instNm", "agency"],
    "posted_at": ["bsnsAncmYmd", "ancmDt", "postDate", "regDt"],
    "deadline_at": ["rcptEndYmd", "rcptEndDt", "endDate", "deadline"],
    "url": ["bsnsAncmDtlUrl", "detailUrl", "url", "linkUrl"],
    "summary": ["bsnsAncmCn", "bsnsSumry", "summary", "ancmCn"],
    "department": ["chrgDeptNm", "deptNm", "department"],
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

        rows_per_page = 50
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
                # JSON 실패 시 XML 한 번 더 시도
                if page == 1 and "<" in r.text[:100]:
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
        """XML 응답 파싱 (JSON 미지원 시)."""
        try:
            from xml.etree import ElementTree as ET
            root = ET.fromstring(text)
            items = []
            for item in root.iter("item"):
                items.append({child.tag: (child.text or "").strip() for child in item})
            return items
        except Exception as e:
            log.debug("xml parse fail: %s", e)
            return []

    def _to_announcement(self, item: dict) -> Announcement | None:
        external_id = _pick(item, _FIELD_MAP["external_id"])
        title = _pick(item, _FIELD_MAP["title"])
        if not external_id or not title:
            return None
        return Announcement(
            source=self.source,
            external_id=external_id,
            title=title,
            url=_pick(item, _FIELD_MAP["url"]) or "",
            agency=_pick(item, _FIELD_MAP["agency"]),
            posted_at=_pick(item, _FIELD_MAP["posted_at"]),
            deadline_at=_pick(item, _FIELD_MAP["deadline_at"]),
            summary=_pick(item, _FIELD_MAP["summary"]),
        )

    def _is_iitp(self, a: Announcement, raw: dict) -> bool:
        """IITP가 발주한 공고인지 추정. 담당기관·제목·부서명에 IITP/정보통신기획평가원 포함."""
        keys = " ".join(
            filter(None, [
                a.agency, a.title,
                _pick(raw, _FIELD_MAP["department"]) or "",
            ])
        ).lower()
        return ("iitp" in keys) or ("정보통신기획평가원" in keys)
