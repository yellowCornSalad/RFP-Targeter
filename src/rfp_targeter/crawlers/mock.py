"""Mock 크롤러 — 실제 사이트가 막힐 때 파이프라인 검증용.

샘플 공고 5개를 반환. 보안 키워드 포함/미포함이 섞여 있어
필터·점수·대시보드 전체 흐름을 테스트할 수 있음.

운영에서는 settings.yaml 에서 enabled: false 권장.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Iterator

from rfp_targeter.crawlers.base import BaseCrawler
from rfp_targeter.db.models import Announcement


def _days(n: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=n)).isoformat(timespec="seconds")


SAMPLES = [
    {
        "external_id": "MOCK-2026-001",
        "title": "AI 기반 사이버위협 자동 탐지·대응 기술 개발",
        "agency": "IITP",
        "budget_mw": 1500,
        "duration_months": 36,
        "summary": (
            "공공·금융 부문 사이버 침해 대응을 위한 AI 기반 위협 탐지·자동화 대응 "
            "(SOAR) 통합 플랫폼 개발. 모의해킹·취약점 분석 자동화 포함."
        ),
        "deadline_at": _days(20),
    },
    {
        "external_id": "MOCK-2026-002",
        "title": "양자내성암호(PQC) 적용 검증체계 구축",
        "agency": "KISA",
        "budget_mw": 900,
        "duration_months": 24,
        "summary": "NIST PQC 표준 알고리즘의 국내 공공·금융 인프라 적용 검증 도구 개발",
        "deadline_at": _days(30),
    },
    {
        "external_id": "MOCK-2026-003",
        "title": "스마트팩토리 OT 보안 침투시험 자동화 기술",
        "agency": "IITP",
        "budget_mw": 2200,
        "duration_months": 36,
        "summary": "산업제어시스템(ICS) 대상 화이트해커 기반 침투시험 자동화 + 보안성 검증",
        "deadline_at": _days(15),
    },
    {
        "external_id": "MOCK-2026-004",
        "title": "고속도로 톨게이트 CCTV 시스템 고도화",
        "agency": "국토교통부",
        "budget_mw": 5000,
        "duration_months": 18,
        "summary": "고속도로 영상 모니터링 시스템 — 물리보안·출입 통제 위주",
        "deadline_at": _days(40),
    },
    {
        "external_id": "MOCK-2026-005",
        "title": "제로트러스트 기반 클라우드 보안 아키텍처 실증",
        "agency": "과기정통부",
        "budget_mw": 600,
        "duration_months": 18,
        "summary": "공공기관 SaaS 환경에 제로트러스트 적용 — 인증·인가·세션 통제",
        "deadline_at": _days(10),
    },
]


class MockCrawler(BaseCrawler):
    source = "mock"
    display_name = "Mock (테스트용)"

    def list_announcements(self) -> Iterator[Announcement]:
        for s in SAMPLES:
            yield Announcement(
                source=self.source,
                external_id=s["external_id"],
                title=s["title"],
                url=f"https://example.test/mock/{s['external_id']}",
                agency=s["agency"],
                posted_at=_days(-2),
                deadline_at=s["deadline_at"],
                budget_mw=s["budget_mw"],
                duration_months=s["duration_months"],
                summary=s["summary"],
                body=s["summary"],  # mock에서는 동일
            )
