"""크롤러 모듈. CRAWLERS 레지스트리에 모두 등록되어 있어야 함."""
from __future__ import annotations

from rfp_targeter.crawlers.base import BaseCrawler

# 신규 어댑터 추가 시 여기에 등록
from rfp_targeter.crawlers.bizinfo import BizinfoCrawler
from rfp_targeter.crawlers.iitp import IITPCrawler
from rfp_targeter.crawlers.kisa import KISACrawler
from rfp_targeter.crawlers.mock import MockCrawler
from rfp_targeter.crawlers.mss import MSSCrawler

CRAWLERS: dict[str, type[BaseCrawler]] = {
    "bizinfo": BizinfoCrawler,
    "iitp": IITPCrawler,
    "kisa": KISACrawler,
    "mock": MockCrawler,
    "mss": MSSCrawler,
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
