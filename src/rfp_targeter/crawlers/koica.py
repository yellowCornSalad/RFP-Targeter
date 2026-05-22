"""KOICA (한국국제협력단) 입찰공고 크롤러 — data.go.kr OpenAPI 기반.

소스: 한국국제협력단_KOICA ODA 조달 정보 (data.go.kr/data/3039908)
- Base: http://openapi.koica.go.kr/api/ws/PrcureService/
- Op: getOrprPlanInfoList (연간발주계획), 입찰목록, 수의계약목록
- serviceKey 필요 (config/secrets.yaml의 data_go_kr.service_key 재사용)

회사 관점: ODA 사이버보안 사업이 간헐적으로 발주됨 (해외 정부 시스템 구축, 디지털
인프라 보안 컨설팅 등). 키워드 필터로 자동 추림.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Iterator
from urllib.parse import urlencode

import requests
from xml.etree import ElementTree as ET

from rfp_targeter.config import secrets
from rfp_targeter.crawlers.base import BaseCrawler
from rfp_targeter.db.models import Announcement

log = logging.getLogger(__name__)

# KOICA OpenAPI base — 연간발주계획 endpoint
# 2026-05 검증: openapi.koica.go.kr 직접 endpoint = unreachable (Connection timeout)
# 대신 data.go.kr 통합 게이트웨이(apis.data.go.kr/3039908) 사용 — 살아있음.
ENDPOINT_PRIMARY = "https://apis.data.go.kr/3039908/OdaPosbnsAList/getSttofnationCoopOdaPosbnsAList"
ENDPOINT_FALLBACK = "http://openapi.koica.go.kr/api/ws/PrcureService/getOrprPlanInfoList"
ENDPOINT = ENDPOINT_PRIMARY  # 기존 호환


class KOICACrawler(BaseCrawler):
    source = "koica"
    display_name = "KOICA"

    def __init__(self, base_url: str | None = None) -> None:
        super().__init__(base_url=base_url or ENDPOINT)
        sec = secrets() or {}
        # KOICA는 data.go.kr 통합 키 사용 — 별도 키 발급도 가능하지만 우선 공유
        self.service_key = (
            (sec.get("koica") or {}).get("service_key")
            or (sec.get("data_go_kr") or {}).get("service_key")
        )

    def list_announcements(self) -> Iterator[Announcement]:
        if not self.service_key or self.service_key == "???":
            log.warning("koica: data.go.kr service_key 미설정 — secrets.yaml 확인. 스킵.")
            return

        # 올해 + 작년 연간발주계획 (1~3월엔 작년 미마감 건이 더 많을 수 있음)
        years = [datetime.now().year, datetime.now().year - 1]
        page_size = min(100, self.max_per_source)
        seen = 0

        for year in years:
            page_no = 1
            while seen < self.max_per_source:
                # data.go.kr 게이트웨이 params (소문자 표준 — primary endpoint)
                params = {
                    "serviceKey": self.service_key,
                    "numOfRows": str(page_size),
                    "pageNo": str(page_no),
                    "P_YEAR": str(year),
                    "P_PAGE_NO": str(page_no),
                    "P_PAGE_SIZE": str(page_size),
                    "type": "xml",
                }
                items = None
                # 1차: data.go.kr 게이트웨이
                for endpoint in (ENDPOINT_PRIMARY, ENDPOINT_FALLBACK):
                    url = f"{endpoint}?{urlencode(params, doseq=True)}"
                    try:
                        r = requests.get(url, timeout=self.timeout)
                        r.raise_for_status()
                        items = self._parse_xml(r.text)
                        if items:
                            break
                    except Exception as e:
                        log.debug("koica %s fetch fail: %s", endpoint[:50], e)
                        continue
                if items is None or len(items) == 0:
                    log.info("koica year=%d: 항목 없음 또는 endpoint 미가용 (page %d)",
                             year, page_no)
                    break

                for it in items:
                    a = self._item_to_announcement(it, year)
                    if a is None:
                        continue
                    yield a
                    seen += 1
                    if seen >= self.max_per_source:
                        break

                if len(items) < page_size:
                    break
                page_no += 1

            if seen >= self.max_per_source:
                break

        log.info("koica: %d건 수집", seen)

    def _parse_xml(self, text: str) -> list[dict]:
        try:
            root = ET.fromstring(text)
        except ET.ParseError as e:
            log.warning("koica xml parse fail: %s", e)
            return []
        out = []
        # 응답 구조: <response>...<items><item>...</item></items></response>
        for item in root.iter("item"):
            row = {}
            for child in item:
                row[child.tag] = (child.text or "").strip()
            out.append(row)
        return out

    def _item_to_announcement(self, it: dict, year: int) -> Announcement | None:
        # 필드 (data.go.kr 명세):
        # - BSNS_NM: 사업명
        # - BID_SCOPE_CN: 입찰범위 (본문)
        # - CNTRCT_MTH_CD: 계약방법코드
        # - RECIPCONTY_NM: 수원국명
        # - BID_LMT_AMOUNT: 예가
        # - ORPR_ERA_YM: 발주예정연월 (YYYYMM)
        # - DEPT_NM: 발주부서
        title = it.get("BSNS_NM") or ""
        if not title:
            return None

        # external_id: BSNS_ID 가 명시 있으면 사용, 없으면 title hash
        ext_id = it.get("BSNS_ID") or it.get("BSNS_NO") or it.get("PBLANC_NO")
        if not ext_id:
            ext_id = f"koica-{year}-{abs(hash(title)) % 10**10}"

        # 발주예정연월 → posted_at (월 1일로 일자 보정)
        posted_at = None
        ym = it.get("ORPR_ERA_YM") or ""
        if re.fullmatch(r"\d{6}", ym):
            posted_at = f"{ym[:4]}-{ym[4:]}-01"

        # 예가 (원 단위) → budget_mw (백만원)
        budget_mw = None
        amt = it.get("BID_LMT_AMOUNT") or ""
        amt_digits = re.sub(r"[^\d]", "", amt)
        if amt_digits.isdigit():
            won = int(amt_digits)
            if won > 0:
                budget_mw = max(1, won // 1_000_000)

        # 발주부서 + 수원국 정보를 agency에 합쳐 표시
        dept = it.get("DEPT_NM") or ""
        country = it.get("RECIPCONTY_NM") or ""
        agency_bits = ["KOICA"]
        if dept:
            agency_bits.append(dept)
        if country:
            agency_bits.append(f"수원국 {country}")
        agency = " · ".join(agency_bits)

        summary = it.get("BID_SCOPE_CN") or None
        if summary and len(summary) > 200:
            summary = summary[:200] + "..."

        # 상세 URL — OpenAPI엔 별도 페이지 URL 없음. 검색 페이지로 폴백
        detail_url = (
            "https://nebid.koica.go.kr/oep/masc/mainPageForm.do"
        )

        return Announcement(
            source=self.source,
            external_id=str(ext_id),
            title=title,
            url=detail_url,
            agency=agency,
            posted_at=posted_at,
            budget_mw=budget_mw,
            summary=summary,
        )

    def fetch_detail(self, a: Announcement) -> Announcement:
        # OpenAPI 응답 자체에 본문(BID_SCOPE_CN)이 들어 있음 → 별도 detail fetch 불필요.
        # 본문이 비어있고 summary만 있다면 summary를 body로 승격.
        if not a.body and a.summary:
            a.body = a.summary
        return a
