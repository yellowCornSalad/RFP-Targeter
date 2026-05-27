"""크롤러 헬스 모니터링 — rfp_crawler 스킬 + GitHub Actions monitor_crawler.yml 공유.

주간 시간(평일 09~18 KST) 동안 매 30분 자동 실행. 비주간은 즉시 skip.

검증:
  1. last fetch_log finished_at 이 60분 초과 안 됐는지
  2. GitHub Actions crawl.yml 최근 5 run 에 cancelled 패턴
  3. 활성 보안 공고 score NULL 0건 (자동 백필 효과 확인)
  4. 슬랙 누락 후보 0건 (영업시간이면 즉시 dispatch)

이상 발견 시:
  - exit code 1 (CI 빨간불)
  - 슬랙 webhook 으로 [모니터] 메시지 발사
  - 표준출력에 진단 결과

사용:
  python scripts/monitor_crawler.py            # 1회 점검
  python scripts/monitor_crawler.py --force    # 비주간 시간도 점검
  python scripts/monitor_crawler.py --silent   # 슬랙 알림 없이 점검만
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rfp_targeter.config import secrets, settings  # noqa: E402
from rfp_targeter.db.models import get_conn  # noqa: E402

try:
    from zoneinfo import ZoneInfo
    KST = ZoneInfo("Asia/Seoul")
except ImportError:
    from datetime import timezone
    KST = timezone(timedelta(hours=9))

log = logging.getLogger("monitor_crawler")

# 임계값
GAP_MINUTES_THRESHOLD = 60        # 마지막 크롤 60분 초과 시 알림
CANCELLED_PATTERN_THRESHOLD = 2   # 최근 5 run 중 2건+ cancelled 시 알림


def _is_business_hours(now: datetime | None = None) -> bool:
    """평일 09~18 KST 영업시간인지."""
    now = now or datetime.now(KST)
    return now.weekday() < 5 and 9 <= now.hour <= 18


def _gh_recent_runs(limit: int = 5) -> list[dict]:
    """gh CLI 로 crawl.yml 최근 run 가져옴. gh 미설치 시 빈 리스트."""
    try:
        r = subprocess.run(
            ["gh", "run", "list", "--workflow=crawl.yml", f"--limit={limit}",
             "--json", "conclusion,createdAt,databaseId"],
            capture_output=True, text=True, timeout=30,
        )
        if r.returncode != 0:
            log.debug("gh CLI 실패: %s", r.stderr[:200])
            return []
        return json.loads(r.stdout or "[]")
    except Exception as e:
        log.debug("gh CLI 호출 실패: %s", e)
        return []


def _send_slack_alert(text: str) -> bool:
    """슬랙 webhook 으로 모니터 알림 발사. 실패해도 조용히 False."""
    webhook = ((secrets().get("slack") or {}).get("webhook_url") or "").strip()
    if not webhook or webhook == "???":
        log.warning("슬랙 webhook 미설정 — 알림 skip")
        return False
    try:
        import requests
        r = requests.post(webhook, json={"text": text}, timeout=10)
        return r.status_code == 200
    except Exception as e:
        log.warning("슬랙 발송 실패: %s", e)
        return False


def dismiss_expired() -> int:
    """신청기한 지난 활성 공고를 is_dismissed=TRUE 로 soft delete.

    - 슬랙·정적 사이트 SQL 은 is_dismissed=FALSE 만 조회 → 자동 제외
    - DB 에는 row 보존 (회고·통계·과거 매칭 데이터 가치)
    - 실수로 dismiss 했어도 UPDATE 한 줄로 복구 가능

    Returns: dismiss 된 건수
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE announcement
                   SET is_dismissed = TRUE
                   WHERE is_dismissed = FALSE
                     AND deadline_at IS NOT NULL
                     AND deadline_at != ''
                     AND deadline_at < CURRENT_DATE::text"""
            )
            return cur.rowcount


def check() -> tuple[bool, list[str]]:
    """크롤러 헬스 점검. Returns (정상 여부, 이슈 목록)."""
    issues: list[str] = []
    now_kst = datetime.now(KST)

    # 만료 공고 dismiss 는 main()에서 비영업시간도 포함해 미리 호출됨 — 여기서 중복 호출 안 함

    # 1) DB 에서 가장 최근 finished_at (UTC text) 가져옴
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT MAX(finished_at) AS last_finished
                   FROM fetch_log WHERE finished_at IS NOT NULL"""
            )
            row = cur.fetchone()
            last_finished_str = row.get("last_finished") if row else None

            # 활성 보안 공고 score NULL
            cur.execute(
                """SELECT COUNT(*) AS n FROM announcement a
                   LEFT JOIN score s ON s.announcement_id = a.id
                   WHERE s.announcement_id IS NULL
                     AND a.is_security = TRUE AND a.is_dismissed = FALSE
                     AND (a.deadline_at >= CURRENT_DATE::text
                          OR (a.deadline_at IS NULL
                              AND a.posted_at >= (CURRENT_DATE - 60)::text))"""
            )
            null_score = cur.fetchone()["n"]

            # 슬랙 누락 후보
            cur.execute(
                """SELECT COUNT(*) AS n FROM announcement a
                   JOIN score s ON s.announcement_id = a.id
                   WHERE a.is_security = TRUE AND a.is_dismissed = FALSE
                     AND a.source IN ('iitp','kisa','krit','nipa','mss','koica')
                     AND s.total_score >= 80
                     AND a.budget_mw IS NOT NULL AND a.budget_mw >= 100
                     AND (a.deadline_at >= CURRENT_DATE::text
                          OR (a.deadline_at IS NULL
                              AND a.posted_at >= (CURRENT_DATE - 60)::text))
                     AND a.alerted_at IS NULL"""
            )
            pending_alerts = cur.fetchone()["n"]

    # 2) 임계 검증
    if last_finished_str:
        # text → datetime (UTC). 다양한 형식 폴백 처리.
        try:
            last_finished = datetime.fromisoformat(
                last_finished_str.replace("Z", "+00:00")
            )
            if last_finished.tzinfo is None:
                from datetime import timezone
                last_finished = last_finished.replace(tzinfo=timezone.utc)
        except Exception:
            last_finished = None
            issues.append(f"finished_at 파싱 실패: {last_finished_str}")

        if last_finished:
            gap = now_kst - last_finished
            gap_minutes = gap.total_seconds() / 60
            if gap_minutes > GAP_MINUTES_THRESHOLD:
                issues.append(
                    f"🚨 크롤러 정지 — 마지막 정상 완료 {gap_minutes:.0f}분 전 "
                    f"({last_finished.astimezone(KST).strftime('%Y-%m-%d %H:%M KST')})"
                )
                # 🔧 자동 복구 — gap > 60분이면 즉시 gh workflow dispatch.
                # concurrency 그룹 'crawl' 이 중복 실행 방지하므로 안전.
                # cooldown: 이미 진행 중인 run 이 있으면 GitHub Actions 가 자동 skip.
                try:
                    r = subprocess.run(
                        ["gh", "workflow", "run", "crawl.yml", "--ref", "main"],
                        capture_output=True, text=True, timeout=20,
                    )
                    if r.returncode == 0:
                        issues.append("  ↳ [자동조치] gh workflow run crawl.yml 즉시 dispatch")
                    else:
                        issues.append(f"  ↳ [자동조치 실패] gh dispatch: {r.stderr[:100]}")
                except Exception as e:
                    issues.append(f"  ↳ [자동조치 실패] {e}")
    else:
        issues.append("⚠ fetch_log 에 finished_at 없음 — 한 번도 정상 완료된 사이클 없음")

    # 3) GitHub Actions 최근 run 패턴
    recent = _gh_recent_runs(limit=5)
    if recent:
        cancelled = sum(1 for r in recent if r.get("conclusion") == "cancelled")
        failures = sum(1 for r in recent if r.get("conclusion") == "failure")
        if cancelled >= CANCELLED_PATTERN_THRESHOLD:
            issues.append(
                f"⚠ GitHub Actions crawl.yml 최근 5 run 중 {cancelled}건 cancelled "
                f"(timeout 패턴 추정)"
            )
        if failures > 0:
            issues.append(
                f"⚠ GitHub Actions crawl.yml 최근 5 run 중 {failures}건 failure"
            )

    # 4) score NULL — 안전망 효과 확인
    if null_score > 0:
        issues.append(
            f"⚠ 활성 보안 공고 중 score NULL {null_score}건 "
            f"(`python scripts/backfill_scores.py` 권장)"
        )

    # 5) 슬랙 누락 후보 — 영업시간이면 즉시 dispatch
    if pending_alerts > 0:
        if _is_business_hours(now_kst):
            try:
                from rfp_targeter.notifier.slack import dispatch_pending_alerts
                sent = dispatch_pending_alerts()
                print(f"[자동조치] 슬랙 누락 {pending_alerts}건 dispatch — sent={sent}")
            except Exception as e:
                issues.append(f"⚠ 슬랙 누락 {pending_alerts}건 dispatch 실패: {e}")
        else:
            print(f"[참고] 슬랙 누락 {pending_alerts}건 누적 — 비영업시간이라 보류")

    return len(issues) == 0, issues


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="비영업시간도 점검")
    ap.add_argument("--silent", action="store_true", help="슬랙 알림 보내지 않음")
    args = ap.parse_args()

    now_kst = datetime.now(KST)
    print(f"=== rfp_crawler 모니터 — {now_kst.strftime('%Y-%m-%d %H:%M %a')} KST ===")

    # 만료 공고 dismiss 는 비영업시간에도 실행 — 24/7 정리
    try:
        n = dismiss_expired()
        if n > 0:
            print(f"[자동조치] 만료 공고 {n}건 dismiss (soft delete)")
    except Exception as e:
        print(f"⚠ dismiss 실패: {e}")

    if not args.force and not _is_business_hours(now_kst):
        print("비영업시간 (평일 09~18 KST 외) — 점검 skip (dismiss 만 수행됨)")
        return 0

    ok, issues = check()
    if ok:
        print("✅ 모든 점검 통과 — 크롤러 정상")
        return 0

    print(f"❌ 이슈 {len(issues)}건 감지:")
    for i in issues:
        print(f"  • {i}")

    # 슬랙 알림
    if not args.silent:
        msg = (
            f"🚨 *[RFP-Targeter 모니터]* {now_kst.strftime('%Y-%m-%d %H:%M KST')}\n"
            + "\n".join(f"• {i}" for i in issues)
            + "\n\n조치 권장: `gh workflow run crawl.yml --ref main` (수동 트리거)"
        )
        _send_slack_alert(msg)

    return 1


if __name__ == "__main__":
    sys.exit(main())
