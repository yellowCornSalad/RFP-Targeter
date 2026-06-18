"""크롤러 모듈. CRAWLERS 레지스트리에 모두 등록되어 있어야 함."""
from __future__ import annotations

from rfp_targeter.crawlers.base import BaseCrawler

# 신규 어댑터 추가 시 여기에 등록
from rfp_targeter.crawlers.bizinfo import BizinfoCrawler
from rfp_targeter.crawlers.g2b import G2BCrawler
from rfp_targeter.crawlers.iitp import IITPCrawler
from rfp_targeter.crawlers.iris import IRISCrawler
from rfp_targeter.crawlers.kisa import KISACrawler
from rfp_targeter.crawlers.koica import KOICACrawler
from rfp_targeter.crawlers.kosa import KOSACrawler
from rfp_targeter.crawlers.krit import KRITCrawler
from rfp_targeter.crawlers.mock import MockCrawler
from rfp_targeter.crawlers.mss import MSSCrawler
from rfp_targeter.crawlers.nipa import NIPACrawler
from rfp_targeter.crawlers.ntis import NTISCrawler

CRAWLERS: dict[str, type[BaseCrawler]] = {
    "bizinfo": BizinfoCrawler,
    "g2b": G2BCrawler,           # 신규 — KOICA 등 G2B 통합 채널
    "iitp": IITPCrawler,
    "iris": IRISCrawler,    # 범부처 R&D 통합 — 2026-06 활성
    "kisa": KISACrawler,
    "koica": KOICACrawler,
    "kosa": KOSACrawler,
    "krit": KRITCrawler,
    "mock": MockCrawler,
    "mss": MSSCrawler,
    "nipa": NIPACrawler,
    "ntis": NTISCrawler,
}


def enabled_crawlers(settings_dict: dict) -> list[BaseCrawler]:
    """settings.yaml에서 enabled=true 인 소스만 인스턴스화."""
    crawlers = []
    for name, src in (settings_dict.get("sources") or {}).items():
        if not src.get("enabled"):
            continue
        cls = CRAWLERS.get(name)
        if cls is None:
            continue  # 미구현 어댑터는 조용히 스킵
        crawlers.append(cls(base_url=src.get("base_url")))
    return crawlers
