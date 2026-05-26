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


def _ext_pri(name: str) -> int:
    """첨부 확장자 우선순위 (작은 값 우선)."""
    n = (name or "").lower()
    if n.endswith(".hwpx"): return 0
    if n.endswith(".pdf"):  return 1
    if n.endswith(".docx"): return 2
    if n.endswith(".odt"):  return 8
    if n.endswith(".hwp"):  return 9
    return 5


def enrich_body_with_attachments(
    a: Announcement,
    referer: str | None = None,
    max_attachments: int = 2,
) -> Announcement:
    """첨부 파일 1~2개 다운로드 + 텍스트 추출 → a.body 에 [첨부 본문] 합쳐 추가.

    공통 헬퍼 — IITP 외 KISA/NIPA 어댑터에서도 동일하게 키워드 추출용 본문 보강.

    동작:
    - a.attachments 가 있어야 함 (어댑터가 list 단계에서 첨부 메타 채워둠)
    - 카테고리 우선순위 (notice > form > 그 외) + 확장자 우선순위 (hwpx > pdf)
    - notice/form 카테고리 만 다운로드 (eval/reference는 메타만 유지)
    - 다운로드/추출 실패해도 a 그대로 반환 (예외 절대 안 던짐)
    - body 합쳐도 10K자 상한 (DB 부담)
    """
    if not a.attachments:
        return a
    # lazy import — base.py가 attachments 모듈 의존하지 않게
    from rfp_targeter.attachments import classify, priority, download_file, extract_text

    # 카테고리 미분류 보강
    for att in a.attachments:
        if not att.get("category"):
            att["category"] = classify(att.get("name", ""))

    sorted_atts = sorted(
        a.attachments,
        key=lambda x: (priority(x.get("category", "other")), _ext_pri(x.get("name", ""))),
    )

    extracted_text = ""
    processed = 0
    for att in sorted_atts:
        if processed >= max_attachments:
            break
        cat = att.get("category", "other")
        if cat not in ("notice", "form"):
            continue
        url = att.get("url")
        name = att.get("name") or "attachment.bin"
        if not url:
            continue
        try:
            path = download_file(url, a.external_id, name, referer=referer)
        except Exception:
            continue
        if path is None:
            continue
        att["local_path"] = str(path)
        try:
            t = extract_text(path)
        except Exception:
            t = None
        if t:
            # PDF 추출 시 NUL 바이트 들어오면 PostgreSQL UPDATE 실패 → 사전 제거
            t = t.replace("\x00", "")
            extracted_text += "\n\n" + t
            processed += 1
            # notice 1개 추출되면 form 까지 안 가도 충분
            if cat == "notice":
                break

    if extracted_text:
        # 기존 body + 첨부 본문 합치기 (10K자 상한) + NUL 바이트 안전 제거
        merged = (a.body or "") + "\n\n[첨부 본문]\n" + extracted_text
        merged = merged.replace("\x00", "")
        a.body = merged[:10000]
    return a


class BaseCrawler(ABC):
    source: str = ""           # 서브클래스에서 오버라이드
    display_name: str = ""

    def __init__(self, base_url: str | None = None) -> None:
        cfg = settings()["crawl"]
        src_cfg = settings().get("sources", {}).get(self.source, {})
        self.base_url = base_url
        self.delay = cfg["request_delay_seconds"]
        self.timeout = cfg["timeout_seconds"]
        # source별 override 우선
        self.max_per_source = src_cfg.get("max_per_source", cfg["max_per_source"])
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
