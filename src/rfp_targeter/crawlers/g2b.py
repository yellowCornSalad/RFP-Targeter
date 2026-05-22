"""G2B (나라장터) 입찰공고 크롤러 — data.go.kr 15129394 OpenAPI.

소스: 조달청_나라장터_입찰공고정보서비스 v05
  endpoint: https://apis.data.go.kr/1230000/ad/BidPublicInfoService/...
  데이터: 한국 모든 공공기관 입찰공고 통합 (KOICA·국방·지자체 등)

회사 관점:
- KOICA 직접 채널이 모두 unreachable인 상황에서 G2B 통해 우회 수집
- KOICA / 외교부 산하 기관 등 키워드 필터로 선택
- 다른 source(KISA·IITP 등)에 없는 발주처 흡수

필요: data.go.kr에서 별도 활용신청 → secrets.yaml의 g2b.service_key
"""
from __future__ import annotations

import logging
import re
from typing import Iterator
from urllib.parse import urlencode
from xml.etree import ElementTree as ET

import requests

from rfp_targeter.config import secrets
from rfp_targeter.crawlers.base import BaseCrawler
from rfp_targeter.db.models import Announcement

log = logging.getLogger(__name__)

ENDPOINT = "https://apis.data.go.kr/1230000/ad/BidPublicInfoService/getBidPblancListInfoServcPPSSrch"

# KOICA·외교부·국제협력 관련 발주처 키워드 — 이걸로 G2B 결과 필터
KOICA_DEMANDORG_KEYWORDS = [
    "한국국제협력단", "KOICA",
    "외교부", "재외동포청",
    # ODA 사업 다른 발주처
    "한국국제보건의료재단", "KOFIH",
]


class G2BCrawler(BaseCrawler):
    """G2B 통합 + KOICA 키워드 필터링."""

    source = "koica"  # KOICA 발주만 가져오므로 source=koica 그대로 사용
    display_name = "KOICA via G2B"

    def __init__(self, base_url: str | None = None) -> None:
        super().__init__(base_url=base_url or ENDPOINT)
        sec = secrets() or {}
        # G2B 전용 키 → 없으면 data.go.kr 공통 키 (둘 다 같은 게이트웨이라 작동 가능성)
        self.service_key = (
            (sec.get("g2b") or {}).get("service_key")
            or (sec.get("data_go_kr") or {}).get("service_key")
        )

    def list_announcements(self) -> Iterator[Announcement]:
        if not self.service_key or self.service_key == "???":
            log.warning("g2b: service_key 미설정 (KOICA 수집 스킵)")
            return

        from datetime import datetime, timedelta
        # 최근 90일 입찰만
        now = datetime.now()
        from_dt = (now - timedelta(days=90)).strftime("%Y%m%d") + "0000"
        to_dt = now.strftime("%Y%m%d") + "2359"

        page = 1
        seen = 0
        while seen < self.max_per_source:
            params = {
                "serviceKey": self.service_key,
                "numOfRows": "100",
                "pageNo": str(page),
                "inqryDiv": "1",  # 1: 등록일자 기준
                "inqryBgnDt": from_dt,
                "inqryEndDt": to_dt,
                "type": "xml",
            }
            url = f"{ENDPOINT}?{urlencode(params)}"
            try:
                r = requests.get(url, timeout=self.timeout)
                r.raise_for_status()
            except Exception as e:
                log.warning("g2b page %d fetch fail: %s", page, e)
                break

            items = self._parse_xml(r.text)
            if not items:
                break

            for it in items:
                a = self._item_to_announcement(it)
                if a is None:
                    continue
                yield a
                seen += 1
                if seen >= self.max_per_source:
                    break

            if len(items) < 100:
                break
            page += 1

        log.info("g2b (KOICA 필터): %d건 수집", seen)

    def _parse_xml(self, text: str) -> list[dict]:
        try:
            root = ET.fromstring(text)
        except ET.ParseError as e:
            log.warning("g2b xml parse fail: %s — body: %s", e, text[:300])
            return []
        out = []
        for item in root.iter("item"):
            row = {child.tag: (child.text or "").strip() for child in item}
            out.append(row)
        return out

    def _item_to_announcement(self, it: dict) -> Announcement | None:
        title = it.get("bidNtceNm") or ""
        if not title:
            return None

        # KOICA 필터 — 발주처 또는 수요기관이 KOICA 관련이면 통과
        demand_org = (it.get("dminsttNm") or "") + " " + (it.get("ntceInsttNm") or "")
        if not any(kw in demand_org for kw in KOICA_DEMANDORG_KEYWORDS):
            return None

        ext_id = it.get("bidNtceNo") or it.get("bidNtceOrd") or ""
        if not ext_id:
            return None

        # URL — 나라장터 입찰 공고 상세
        bid_url = it.get("bidNtceDtlUrl") or (
            f"http://www.g2b.go.kr:8101/ep/invitation/publish/bidInfoDtl.do"
            f"?bidno={ext_id}"
        )

        posted_at = self._date_only(it.get("bidNtceDate") or it.get("rgstDt") or "")
        deadline = self._date_only(it.get("bidClseDate") or "")

        amt_str = it.get("presmptPrce") or ""
        budget_mw = None
        amt_digits = re.sub(r"[^\d]", "", amt_str)
        if amt_digits.isdigit():
            won = int(amt_digits)
            if won > 0:
                budget_mw = max(1, won // 1_000_000)

        return Announcement(
            source="koica",  # KOICA 발주만 통과시키므로
            external_id=str(ext_id),
            title=title,
            url=bid_url,
            agency=demand_org.strip() or "한국국제협력단",
            posted_at=posted_at,
            deadline_at=deadline,
            budget_mw=budget_mw,
            summary=None,
        )

    def _date_only(self, dt_str: str) -> str | None:
        """'20260521143000' 또는 '2026-05-21' → 'YYYY-MM-DD'."""
        d = re.sub(r"[^\d]", "", dt_str)
        if len(d) >= 8:
            return f"{d[:4]}-{d[4:6]}-{d[6:8]}"
        return None
