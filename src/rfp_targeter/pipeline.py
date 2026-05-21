"""파이프라인 오케스트레이션: 크롤링 → 보안 필터 → DB 저장 → 점수 산정 → (선택) 초안 생성."""
from __future__ import annotations

import logging
from dataclasses import dataclass

from rfp_targeter.attachments.budget_extract import extract_budget_info
from rfp_targeter.config import settings
from rfp_targeter.crawlers import enabled_crawlers
from rfp_targeter.db.models import (
    Announcement, get_conn, init_db, log_fetch_finish, log_fetch_start,
    upsert_announcement, upsert_score,
)
from rfp_targeter.config import profile
from rfp_targeter.filters.eligibility import check_eligibility
from rfp_targeter.filters.security_filter import SecurityFilter
from rfp_targeter.notifier.slack import notify_new_announcements
from rfp_targeter.scoring import compute_score

log = logging.getLogger(__name__)


@dataclass
class RunStats:
    source: str
    new: int = 0
    updated: int = 0
    filtered_in: int = 0
    error: str | None = None


def _enrich_budget(a: Announcement) -> None:
    """본문에서 예산 + 기간 + 원문 발췌 추출 (hallucination 방지 — 본문에 있는 값만).

    크롤러가 이미 a.budget_mw 채웠더라도 더 정확/풍부한 정보 발견하면 보강.
    못 찾으면 그대로 None (가짜 값 절대 X).
    """
    if not a.body:
        return
    info = extract_budget_info(a.body)
    if not info:
        return
    # 크롤러가 더 신뢰할 만한 값 채웠으면 우선 (예: API 직접 응답)
    if a.budget_mw is None:
        a.budget_mw = info.mw
    a.budget_period = info.period_label
    a.budget_excerpt = info.raw_excerpt
    a.budget_confidence = info.confidence
    if a.duration_months is None and info.duration_months:
        a.duration_months = info.duration_months


def run_once() -> list[RunStats]:
    """모든 활성 크롤러 1회 실행."""
    init_db()
    sec_filter = SecurityFilter()
    # 회사 설립 연도 — 자격(창업 N년차) 검증용. profile.yaml에서 1회 로드.
    _company = (profile() or {}).get("company") or {}
    _established_year = _company.get("established_year")
    if not isinstance(_established_year, int):
        _established_year = None
    stats: list[RunStats] = []

    # 사이클 동안 추가된 신규 보안 공고 모음 — 마지막에 슬랙 일괄 발송
    cycle_new_alerts: list = []  # [(Announcement, Score), ...]

    for crawler in enabled_crawlers(settings()):
        s = RunStats(source=crawler.source)
        with get_conn() as conn:
            log_id = log_fetch_start(conn, crawler.source)

        try:
            for a in crawler.list_announcements():
                # 본문 보강 — 어댑터에 따라 무시될 수 있음
                a = crawler.fetch_detail(a)

                # 예산·기간·원문 발췌 보강 (본문 명시값만, hallucination 방지)
                _enrich_budget(a)

                # 1차: 보안 키워드 필터 (제목·요약·본문 + 부서명 화이트리스트)
                fr = sec_filter.check(a.title, a.summary, a.body, agency=a.agency)
                a.is_security = fr.passed
                a.matched_keywords = fr.matched + fr.boost_matched

                # 자격 검증 — 창업 N년차 vs 공고의 자격 조건. 점수는 변경 X (배지 표시용).
                er = check_eligibility(
                    body=a.body, title=a.title,
                    established_year=_established_year,
                )
                a.eligibility_status = er.status
                a.eligibility_note = er.note
                a.eligibility_limit = er.limit_years

                # 보안 필터 통과한 것만 점수 산정. 미통과도 DB에 저장 (감사 추적)
                with get_conn() as conn:
                    is_new = upsert_announcement(conn, a)
                    if is_new:
                        s.new += 1
                    else:
                        s.updated += 1
                    if a.is_security:
                        s.filtered_in += 1
                        score = compute_score(a)
                        upsert_score(conn, score)
                        # 이번 사이클 신규 + 보안 통과 → 슬랙 알림 대상
                        if is_new:
                            cycle_new_alerts.append((a, score))

            with get_conn() as conn:
                log_fetch_finish(conn, log_id, s.new, s.updated)
        except Exception as e:
            log.exception("Pipeline error in %s", crawler.source)
            s.error = str(e)
            with get_conn() as conn:
                log_fetch_finish(conn, log_id, s.new, s.updated, error=str(e))

        log.info(
            "[%s] 신규 %d / 업데이트 %d / 보안통과 %d",
            crawler.source, s.new, s.updated, s.filtered_in,
        )
        stats.append(s)

    # 사이클 끝 — 신규 보안 공고가 1건+ 있으면 슬랙 일괄 발송
    if cycle_new_alerts:
        from datetime import datetime as _dt
        cycle_label = _dt.now().strftime("%Y-%m-%d %H:%M")
        try:
            notify_new_announcements(cycle_new_alerts, cycle_label=cycle_label)
        except Exception:
            # 알림 실패가 파이프라인 전체를 죽이지 않게
            log.exception("slack alert dispatch failed (pipeline 계속)")

    return stats
