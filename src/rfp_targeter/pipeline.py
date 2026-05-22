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
from rfp_targeter.notifier.slack import dispatch_pending_alerts
from rfp_targeter.scoring import compute_score

log = logging.getLogger(__name__)


@dataclass
class RunStats:
    source: str
    new: int = 0
    updated: int = 0
    filtered_in: int = 0
    error: str | None = None


_REQUIRED_SOURCES = {
    "kisa": "KISA", "kosa": "KOSA", "iitp": "IITP",
    "krit": "KRIT", "koica": "KOICA", "nipa": "NIPA",
    "mss": "중기부",
}


# 첨부 추출률 회귀 감지 — Slack 경보 임계값 (사용자 명시: KISA 50건+ 유지)
_ATT_RATE_ALERT_THRESHOLD = {
    "kisa": 80.0,  # 입찰공고는 첨부 거의 100%여야
    "nipa": 80.0,
    "mss":  80.0,
    "iitp": 90.0,
    # kosa/krit는 본문에 첨부 자체 없는 게 정상 — 모니터 제외
}


def _alert_attachment_regression(db_counts: dict[str, tuple[int, int]]) -> None:
    """첨부 추출률이 임계값 미만이면 Slack 경보. 회귀 즉시 감지용.

    이 함수는 cron 끝에 호출됨. 만약 KISA 첨부율이 50% 미만이면
    "긴급 회귀" 메시지를 Slack에 push.
    """
    regressions = []
    for src, threshold in _ATT_RATE_ALERT_THRESHOLD.items():
        total, att = db_counts.get(src, (0, 0))
        if total < 5:  # 데이터 너무 적으면 노이즈 — 패스
            continue
        rate = 100 * att / total
        if rate < threshold:
            regressions.append({
                "source": src,
                "total": total,
                "with_att": att,
                "rate": rate,
                "threshold": threshold,
            })
    if not regressions:
        return

    log.warning("⚠ 첨부 회귀 감지 %d건 — Slack 경보 push", len(regressions))
    # Slack webhook 호출
    try:
        from rfp_targeter.notifier.slack import _post_webhook  # type: ignore
        lines = ["🚨 *첨부 추출률 회귀 감지*"]
        for r in regressions:
            lines.append(
                f"• `{r['source']}`: {r['with_att']}/{r['total']}건 "
                f"({r['rate']:.0f}%) — 임계 {r['threshold']:.0f}% 미만"
            )
        lines.append("`scripts/backfill_attachments.py` 실행 권장")
        _post_webhook({"text": "\n".join(lines)})
    except Exception:
        log.exception("회귀 경보 Slack 발송 실패")


def _verify_required_sources(stats: list) -> None:
    """매 크롤 사이클 끝에 사용자 명시 7개 source + 첨부 누락 감지.

    사용자 요구: KISA · KOSA · IITP · KRIT · KOICA · NIPA · 중기부(MSS)
    이번 사이클 stats + DB 실제 카운트 둘 다 검증.
    어느 하나라도 0건/비활성화/에러면 WARNING 로그.
    """
    stat_by_src = {s.source: s for s in stats}

    # DB 실제 카운트로 누락/첨부 상태 점검
    db_counts: dict[str, tuple[int, int]] = {}  # src → (total, with_att)
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT source, COUNT(*) AS total,
                              COUNT(*) FILTER (WHERE attachments_json IS NOT NULL
                                               AND attachments_json NOT IN ('','[]')) AS with_att
                       FROM announcement GROUP BY source"""
                )
                for r in cur.fetchall():
                    db_counts[r["source"]] = (r["total"], r["with_att"])
    except Exception:
        log.exception("verify: DB 카운트 조회 실패")

    issues = []
    summaries = []
    for src, name in _REQUIRED_SOURCES.items():
        s = stat_by_src.get(src)
        total, att = db_counts.get(src, (0, 0))
        att_rate = (100 * att / total) if total else 0
        summaries.append(f"{name}({src}): DB {total}건 · 첨부 {att_rate:.0f}%")

        if s is None and total == 0:
            issues.append(f"{name}({src}) 비활성화 + DB 0건")
        elif s and s.error:
            issues.append(f"{name}({src}) 에러: {s.error[:80]}")
        elif total == 0:
            issues.append(f"{name}({src}) DB 0건 — 어댑터 점검 필요")
        elif total > 5 and att_rate < 30 and src not in ("kosa", "krit"):
            # kosa/krit은 본문에 첨부 자체 없는 게 정상
            issues.append(f"{name}({src}) 첨부 추출률 {att_rate:.0f}% — 추가 백필 필요")

    log.info("=== 필수 7개 source 상태 ===")
    for s in summaries:
        log.info("  · %s", s)
    if issues:
        log.warning("⚠ 점검 필요 %d건:", len(issues))
        for i in issues:
            log.warning("  ✗ %s", i)
    else:
        log.info("✓ 모든 7개 source 정상")

    # 회귀 자동 경보 — KISA/NIPA/MSS/IITP 첨부율 임계값 미만이면 Slack 즉시 알림
    try:
        _alert_attachment_regression(db_counts)
    except Exception:
        log.exception("회귀 경보 호출 실패 (pipeline 계속)")


def _backfill_missing_attachments(max_per_source: int = 100) -> None:
    """크롤 사이클 끝에 호출 — KISA/NIPA/MSS 중 첨부 없는 row 재처리.

    이유: 매시 cron 크롤이 일시적 fetch 실패로 첨부 [] 저장하는 경우
    누적적으로 첨부 누락. 사이클 끝에 가장 최근 N건 재시도해서 복구.
    각 source 당 20건 제한 (cron 시간 폭 보호).
    """
    from rfp_targeter.crawlers.kisa import KISACrawler
    from rfp_targeter.crawlers.nipa import NIPACrawler
    from rfp_targeter.crawlers.mss import MSSCrawler

    candidates = {
        "kisa": KISACrawler,
        "nipa": NIPACrawler,
        "mss":  MSSCrawler,
    }
    for src, cls in candidates.items():
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """SELECT id, source, external_id, title, url, agency,
                                  posted_at, deadline_at, body
                           FROM announcement
                           WHERE source = %s
                           AND (attachments_json IS NULL OR attachments_json IN ('', '[]'))
                           ORDER BY posted_at DESC NULLS LAST
                           LIMIT %s""",
                        (src, max_per_source),
                    )
                    rows = cur.fetchall()
            if not rows:
                continue
            crawler = cls()
            recovered = 0
            for r in rows:
                a = Announcement(
                    source=r["source"], external_id=r["external_id"],
                    title=r["title"], url=r["url"],
                    agency=r["agency"], posted_at=r["posted_at"],
                    deadline_at=r["deadline_at"], body=r["body"] or "",
                )
                try:
                    a = crawler.fetch_detail(a)
                except Exception:
                    continue
                if a.attachments:
                    import json as _json
                    with get_conn() as conn:
                        with conn.cursor() as cur:
                            cur.execute(
                                "UPDATE announcement SET attachments_json=%s WHERE id=%s",
                                (_json.dumps(a.attachments, ensure_ascii=False), r["id"]),
                            )
                    recovered += 1
            if recovered:
                log.info("[%s] 첨부 백필 복구 %d/%d 건", src, recovered, len(rows))
        except Exception:
            log.exception("[%s] 첨부 백필 실패", src)


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

    # ⚠️ 이전엔 cycle_new_alerts 로컬 리스트로 이번 사이클 신규만 즉시 발송했음.
    # 변경: 영업시간(평일 09~18 KST)만 발송하는 요구사항 →
    # 신규 공고는 alerted_at IS NULL 인 채로 DB에 누적되고,
    # dispatch_pending_alerts() 가 영업시간이면 묶음 발송 + alerted_at 표시.
    # → 사이클 끝에 호출 (아래)

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
                        # 신규 + 보안 통과 — upsert_announcement INSERT 분기에서 alerted_at=NULL
                        # 으로 들어옴 → dispatch_pending_alerts() 가 영업시간에 큐 처리

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

    # 사이클 끝 — KISA 등 첨부 누락 row 자동 백필 (Live 사이트에 첨부 있는데 추출 실패한 경우)
    try:
        _backfill_missing_attachments()
    except Exception:
        log.exception("attachment backfill failed (pipeline 계속)")

    # 사이클 끝 — 사용자 명시 7개 source 누락 자동 검증 (사용자 요청)
    try:
        _verify_required_sources(stats)
    except Exception:
        log.exception("source verify failed (pipeline 계속)")

    # 사이클 끝 — 영업시간(평일 09~18 KST)이면 alerted_at IS NULL 보안 신규를 묶음 발송.
    # 영업시간 외엔 누적만, 다음 영업일 09시 첫 cron이 통합 발송.
    # 예: 5/11(월) 21시 신규 → 5/12(화) 09시 cron이 묶음 알림.
    try:
        dispatch_pending_alerts()
    except Exception:
        log.exception("slack dispatch_pending_alerts failed (pipeline 계속)")

    return stats
