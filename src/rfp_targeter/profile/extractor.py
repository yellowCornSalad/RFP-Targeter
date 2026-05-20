"""enkiwhitehat.com 홈페이지에서 회사 프로필 추출.

전략:
1. 메인 페이지 + 주요 하위 페이지(소개·서비스·연구) 크롤링
2. 모든 텍스트를 모은 뒤 키워드 빈도·기술명 추출
3. config/profile.yaml 초안 생성 (사용자가 검수)

LLM 호출 없이 휴리스틱만 사용 — API 키 없는 환경에서도 동작.
LLM 보강이 필요하면 별도 단계로 추가.
"""
from __future__ import annotations

import logging
import re
from collections import Counter
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
import yaml
from bs4 import BeautifulSoup

from rfp_targeter.config import CONFIG_DIR, keywords, settings

log = logging.getLogger(__name__)

# 추출 시 강조할 후보 키워드 (보안 도메인)
CANDIDATE_KEYWORDS = [
    "화이트해커", "모의해킹", "침투시험", "레드팀", "취약점 분석", "취약점분석",
    "보안 자동화", "보안자동화", "버그바운티", "공격 시뮬레이션", "BAS",
    "악성코드 분석", "포렌식", "위협 인텔리전스", "위협인텔리전스",
    "양자내성암호", "PQC", "동형암호", "AI 보안", "클라우드 보안",
    "OT 보안", "IoT 보안", "취약점 진단", "보안성 검증",
]


def _is_internal(base: str, link: str) -> bool:
    bu = urlparse(base)
    lu = urlparse(link)
    return (not lu.netloc) or (lu.netloc == bu.netloc)


def _fetch_text(url: str, timeout: int = 20) -> tuple[str, list[str]]:
    """본문 텍스트와 내부 링크 목록 반환."""
    try:
        r = requests.get(url, timeout=timeout, headers={"User-Agent": settings()["crawl"]["user_agent"]})
        r.raise_for_status()
    except Exception as e:
        log.warning("fetch fail %s: %s", url, e)
        return "", []

    soup = BeautifulSoup(r.text, "lxml")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    text = re.sub(r"\s+", " ", soup.get_text(" ")).strip()
    links = [urljoin(url, a.get("href", "")) for a in soup.find_all("a", href=True)]
    return text, links


def extract_profile(homepage: str | None = None, max_pages: int = 8) -> dict:
    """홈페이지 크롤링 → profile dict 초안."""
    homepage = homepage or settings()["profile_extraction"]["homepage_url"]
    log.info("프로필 추출 시작: %s", homepage)

    visited: set[str] = set()
    queue: list[str] = [homepage]
    all_text = []

    while queue and len(visited) < max_pages:
        url = queue.pop(0)
        if url in visited:
            continue
        visited.add(url)
        text, links = _fetch_text(url)
        if text:
            all_text.append(text)
        # 동일 도메인 내부 링크만 추가
        for link in links:
            if _is_internal(homepage, link) and link not in visited and len(queue) < max_pages * 2:
                queue.append(link)

    blob = " ".join(all_text).lower()

    # 후보 키워드 빈도
    keyword_hits: list[tuple[str, int]] = []
    for kw in CANDIDATE_KEYWORDS:
        count = blob.count(kw.lower())
        if count > 0:
            keyword_hits.append((kw, count))
    keyword_hits.sort(key=lambda x: -x[1])

    # 보안 키워드 사전과 교집합
    sec_kw_cfg = keywords()["must_any"]
    sec_keywords_found = [kw for kw in sec_kw_cfg if kw.lower() in blob]

    profile = {
        "company": {
            "name": "엔키화이트햇",
            "english_name": "ENKI WhiteHat",
            "homepage": homepage,
            "established_year": "???",
            "size": "???",
        },
        "core_keywords": [k for k, _ in keyword_hits[:8]] or ["???"],
        "_extracted": {
            "keyword_frequency": dict(keyword_hits[:20]),
            "matched_security_keywords": sec_keywords_found[:30],
            "pages_crawled": sorted(visited),
        },
        "technologies": [
            {"name": "???", "trl": "???", "keywords": ["???"]},
        ],
        "budget_range": {
            "min": 300, "sweet_spot_min": 800, "sweet_spot_max": 3000, "max": 5000,
        },
        "consortium": {
            "preferred_role": "주관",
            "max_partners": 3,
            "existing_partners": ["???"],
            "university_partner_available": False,
        },
        "track_record": {"past_awards": [], "reject_patterns": ["???"]},
        "competitors": ["???"],
    }
    return profile


def save_profile_yaml(profile: dict, dest: Path | None = None) -> Path:
    dest = dest or (CONFIG_DIR / "profile.yaml")
    if dest.exists():
        backup = dest.with_suffix(".yaml.bak")
        backup.write_text(dest.read_text(encoding="utf-8"), encoding="utf-8")
        log.info("기존 profile.yaml 백업: %s", backup)
    with dest.open("w", encoding="utf-8") as f:
        f.write("# 자동 추출됨 — 사용자 검수 필요. ???로 표시된 항목 채우기.\n")
        yaml.safe_dump(profile, f, allow_unicode=True, sort_keys=False)
    log.info("저장: %s", dest)
    return dest
