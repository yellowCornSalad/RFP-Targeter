"""크롤러 베이스 클래스."""
from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from typing import Iterator

import requests
from tenacity import retry, stop_after_attempt, wait_exponential

from rfp_targeter.config import settings
from rfp_targeter.db.models import Announcement

log = logging.getLogger(__name__)


class BaseCrawler(ABC):
    source: str = ""           # 서브클래스에서 오버라이드
    display_name: str = ""

    def __init__(self, base_url: str | None = None) -> None:
        cfg = settings()["crawl"]
        self.base_url = base_url
        self.delay = cfg["request_delay_seconds"]
        self.timeout = cfg["timeout_seconds"]
        self.max_per_source = cfg["max_per_source"]
        self.session = requests.Session()
        self.session.headers["User-Agent"] = cfg["user_agent"]

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
    def fetch(self, url: str, **kwargs) -> requests.Response:
        log.debug("GET %s", url)
        time.sleep(self.delay)
        r = self.session.get(url, timeout=self.timeout, **kwargs)
        r.raise_for_status()
        return r

    @abstractmethod
    def list_announcements(self) -> Iterator[Announcement]:
        """공고 목록 페이지를 순회하며 Announcement 생성.

        본문(body)·첨부파일은 시간이 오래 걸리므로 별도 단계로 분리할 수도 있음.
        여기서는 단순화: list 단계에서 가능한 만큼 채우고, 부족하면 fetch_detail 호출.
        """

    def fetch_detail(self, announcement: Announcement) -> Announcement:
        """본문·예산·기간·첨부파일 등 상세 정보 보강. 기본은 그대로 반환."""
        return announcement
