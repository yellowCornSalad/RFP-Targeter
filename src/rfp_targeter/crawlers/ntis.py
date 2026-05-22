"""NTIS — 과기정통부 사업공고 API 공유 어댑터 (IITP 제외 부처 흡수).

배경:
- NTIS 본 사이트(ntis.go.kr) robots.txt = `Disallow: /` 전면 차단.
- NTIS 자체 OpenAPI(rndopen)는 "수행된 R&D 과제 검색"이라 사업공고에 부적합.
- 실제로 NTIS 통합공고가 노출하는 사업공고 데이터 = data.go.kr 15074634
  (= 과학기술정보통신부 사업공고 = 과기정통부 산하 전 부처 통합)
  → IITP 어댑터가 이미 같은 endpoint를 사용 중.

이 어댑터의 역할:
  IITP 어댑터는 `iitp_only_filter=True` 로 IITP 공고만 거름.
  NTIS 어댑터는 동일 endpoint 호출 + IITP 매칭된 항목을 거꾸로 제외 →
  나머지 부처(NIA, ETRI, KEIT, KCA, 한국연구재단, KISTEP 등) 흡수.

중복 우려:
  source 컬럼이 'iitp' vs 'ntis' 로 다르므로 DB UNIQUE 제약으로 충돌 안 남.
  단 IITP 공고가 양쪽에 들어가지 않게 _is_iitp 역필터 필수.
"""
from __future__ import annotations

import logging
from typing import Iterator
from urllib.parse import unquote, urlencode

from rfp_targeter.crawlers.iitp import IITPCrawler
from rfp_targeter.db.models import Announcement

log = logging.getLogger(__name__)


class NTISCrawler(IITPCrawler):
    source = "ntis"
    display_name = "NTIS (과기정통부 산하 · IITP 제외)"

    def __init__(self, base_url: str | None = None) -> None:
        super().__init__(base_url=base_url)
        # 부모의 IITP 필터 비활성화 (모든 부처 항목을 일단 받음)
        self.iitp_only = False

    def list_announcements(self) -> Iterator[Announcement]:
        # ⚠️ 사용자 명시 7개 source 목록에 NTIS 없음 + IITP와 100% 중복.
        # 이중 안전장치 — settings.yaml에 enabled=false 외에도 어댑터 자체에서 차단.
        log.info("ntis: 사용자 목록 외 source — 강제 비활성화 (IITP가 동일 데이터 흡수)")
        return
        # 아래는 미래 NTIS endpoint가 IITP와 다른 데이터 줄 때 부활 (현재는 unreachable)
        # noinspection PyUnreachableCode
        _ = super().list_announcements()
        if not self.service_key or self.service_key == "???":
            log.warning(
                "NTIS: data.go.kr serviceKey 미설정. config/secrets.yaml 확인 필요. "
                "발급: https://www.data.go.kr/data/15074634/openapi.do"
            )
            return

        rows_per_page = 10
        max_pages = max(1, (self.max_per_source + rows_per_page - 1) // rows_per_page)
        seen = 0

        for page in range(1, max_pages + 1):
            sk = unquote(self.service_key)
            params = {
                "serviceKey": sk,
                "pageNo": page,
                "numOfRows": rows_per_page,
                "type": "json",
            }
            url = f"{self.endpoint}?{urlencode(params)}"
            try:
                r = self.fetch(url)
            except Exception as e:
                log.warning("ntis API page %d fail: %s", page, e)
                break

            data = self._parse_response(r)
            items = self._extract_items(data)
            if not items:
                items = self._extract_items_from_xml(r.text)
            if not items:
                log.info("ntis: 항목 없음 (page %d)", page)
                break

            for item in items:
                a = self._to_announcement(item)
                if a is None:
                    continue
                # IITP 항목은 IITP 어댑터가 처리 → NTIS에서는 거꾸로 제외 (중복 방지)
                if self._is_iitp(a, item):
                    continue
                # source 컬럼 'ntis'로 재기입 — 부모 _to_announcement는 self.source 사용
                # NTISCrawler 인스턴스에서 호출되므로 자동으로 'ntis' 들어감
                yield a
                seen += 1
                if seen >= self.max_per_source:
                    log.info("ntis: max_per_source(%d) 도달", self.max_per_source)
                    return

        log.info("ntis: %d건 수집", seen)
