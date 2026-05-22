"""Slack Incoming Webhook 알림 — 신규 보안 공고 발견 시 발송.

사용:
    from rfp_targeter.notifier.slack import notify_new_announcements
    notify_new_announcements(list_of_announcement_score_tuples)

settings.yaml:
    alert:
      slack_enabled: true     # false면 모든 호출 무시
      cycle_summary: true     # 사이클 끝 모음 알림 (기본)

secrets.yaml:
    slack:
      webhook_url: "https://hooks.slack.com/services/T.../B.../xxxxx"

설계 원칙:
- 새 공고가 0건이면 발송 X (조용)
- 1+ 건이면 한 메시지에 모두 묶음 (사이클당 1 알림)
- Block Kit 풍부 메시지: 등급 배지 + 점수 + 기관 + 예산 + 키워드 + 링크
- 자격 미달 공고는 ⚠️ 배지로 명시 (제외 안 함, 사용자 판단)
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Iterable

import requests

try:
    from zoneinfo import ZoneInfo
    KST = ZoneInfo("Asia/Seoul")
except ImportError:
    # Python < 3.9 폴백 (이 프로젝트는 3.11+이라 도달 안 함)
    from datetime import timezone, timedelta
    KST = timezone(timedelta(hours=9))

from rfp_targeter.config import secrets, settings
from rfp_targeter.db.models import Announcement, Score, get_conn

log = logging.getLogger(__name__)

# 대시보드 base URL (settings.yaml에 override 가능)
DEFAULT_DASHBOARD_URL = "https://enkirfp.streamlit.app"

# 영업시간 — 사용자 요청: 평일 09:00 ~ 18:00 KST 만 슬랙 알림
# 그 외 시간 들어온 신규 보안 공고는 alerted_at NULL 인 채로 누적 →
# 다음 영업시간 첫 cron(평일 09시)에 묶음 발송
DEFAULT_BIZ_HOUR_START = 9
DEFAULT_BIZ_HOUR_END = 18  # 18시 정각 cron까지 포함, 19시부터 누적


def _is_business_hours(now: datetime | None = None) -> bool:
    """현재 시각이 평일 09:00 ~ 18:00 KST 인지.

    settings.yaml의 alert.business_hours.{start,end,weekdays_only} 로 오버라이드 가능.
    """
    cfg = ((settings().get("alert") or {}).get("business_hours") or {})
    start_h = int(cfg.get("start", DEFAULT_BIZ_HOUR_START))
    end_h = int(cfg.get("end", DEFAULT_BIZ_HOUR_END))
    weekdays_only = bool(cfg.get("weekdays_only", True))

    now = now or datetime.now(KST)
    if weekdays_only and now.weekday() >= 5:  # 5=Sat, 6=Sun
        return False
    return start_h <= now.hour <= end_h


def _grade(total: float) -> tuple[str, str, str]:
    """(이모지, 등급명, hex 색상)"""
    if total >= 90:
        return "🟠", "TOP", "#f97316"
    if total >= 75:
        return "🟢", "GOOD", "#16a34a"
    if total >= 60:
        return "🟡", "FAIR", "#eab308"
    return "⚪", "LOW", "#94a3b8"


def _agency_label(source: str, agency: str | None) -> str:
    """기관 약어 (KISA / IITP / NTIS ...)"""
    label_map = {
        "kisa": "🛡 KISA", "iitp": "🔬 IITP", "ntis": "🧪 NTIS",
        "kosa": "💻 KOSA", "nipa": "🌐 NIPA", "krit": "🛩 KRIT",
        "mss": "🏭 MSS", "koica": "🌍 KOICA", "bizinfo": "📌 bizinfo",
    }
    prefix = label_map.get(source, source.upper())
    if agency and agency.strip() and agency.strip() not in prefix:
        return f"{prefix} · {agency.strip()}"
    return prefix


def _budget_text(budget_mw: int | None) -> str:
    if budget_mw is None or budget_mw <= 0:
        return "예산 정보 없음"
    if budget_mw >= 1000:
        eok = budget_mw / 1000
        return f"💰 {eok:.1f}억" if eok != int(eok) else f"💰 {int(eok)}억"
    return f"💰 {budget_mw}백만원"


def _deadline_text(deadline_at: str | None) -> str:
    if not deadline_at:
        return ""
    from datetime import datetime
    try:
        d = datetime.fromisoformat(str(deadline_at).split("T")[0])
        days_left = (d.date() - datetime.now().date()).days
        if days_left < 0:
            return f"📅 마감됨 ({deadline_at})"
        if days_left <= 7:
            return f"⏰ 마감 D-{days_left} ({deadline_at})"
        return f"📅 마감 D-{days_left} ({deadline_at})"
    except Exception:
        return f"📅 마감 {deadline_at}"


def _build_attachment(a: Announcement, s: Score, dashboard_url: str) -> dict:
    """Slack message 'attachment' (등급별 색상 사이드바 있는 카드)."""
    emoji, grade, color = _grade(float(s.total_score or 0))

    # 헤더 — 등급 + 점수
    elig_badge = ""
    if a.eligibility_status == "blocked":
        elig_badge = "  ⚠️ 자격 미달"
    elif a.eligibility_status == "unsure":
        elig_badge = "  ❓ 자격 확인 필요"

    header_text = (
        f"*{emoji} {grade}* · 종합 *{s.total_score:.0f}점* "
        f"(테마 {s.theme_fit:.0f}){elig_badge}"
    )

    # 본문
    title = a.title or "(제목 없음)"
    # Slack은 URL을 <URL|text> 형식
    title_line = f"*<{a.url}|{title}>*" if a.url and a.url.startswith("http") else f"*{title}*"

    agency_line = _agency_label(a.source, a.agency)

    meta_parts = []
    bud = _budget_text(a.budget_mw)
    if bud != "예산 정보 없음":
        meta_parts.append(bud)
    dl = _deadline_text(a.deadline_at)
    if dl:
        meta_parts.append(dl)
    meta_line = "  ·  ".join(meta_parts) if meta_parts else ""

    # 매칭 키워드 (최대 6개)
    kws = (a.matched_keywords or [])[:6]
    kws_clean = [k for k in kws if isinstance(k, str) and not k.startswith("[부서]")]
    kws_line = "  ".join(f"`{k}`" for k in kws_clean) if kws_clean else ""

    # 5축 mini
    axes_line = (
        f"5축: 키워드 {s.keyword_score:.0f} · 예산 {s.budget_score:.0f} "
        f"· 컨소시엄 {s.consortium_score:.0f} · 경쟁 {s.competitor_score:.0f} "
        f"· TRL {s.trl_score:.0f}"
    )

    body_lines = [header_text, "", title_line, agency_line]
    if meta_line:
        body_lines.append(meta_line)
    if kws_line:
        body_lines.append(kws_line)
    body_lines.append(axes_line)

    return {
        "color": color,
        "blocks": [
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": "\n".join(body_lines)},
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "원문 보기 ↗"},
                        "url": a.url,
                    } if a.url and a.url.startswith("http") else {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "대시보드"},
                        "url": dashboard_url,
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "📊 대시보드 열기"},
                        "url": dashboard_url,
                    },
                ],
            },
        ],
    }


def notify_new_announcements(
    items: Iterable[tuple[Announcement, Score]],
    cycle_label: str | None = None,
) -> bool:
    """신규 보안 통과 공고들을 한 슬랙 메시지로 발송.

    Args:
        items: [(Announcement, Score), ...] — 이번 사이클 신규
        cycle_label: 메시지 헤더에 표시할 사이클 라벨 (예: "14:50 사이클")

    Returns:
        True 발송 성공 / False (webhook 미설정 또는 0건이라 skip)
    """
    items = list(items)
    if not items:
        return False  # 0건은 조용히 skip

    cfg = (settings().get("alert") or {})
    if not cfg.get("slack_enabled", False):
        log.debug("slack alert disabled (settings.alert.slack_enabled=false)")
        return False

    webhook = ((secrets().get("slack") or {}).get("webhook_url") or "").strip()
    if not webhook or webhook == "???":
        log.warning("slack alert: webhook_url 미설정 (secrets.yaml slack.webhook_url)")
        return False

    dashboard_url = cfg.get("dashboard_url") or DEFAULT_DASHBOARD_URL

    # 메시지 헤더
    n = len(items)
    header = f"📢 *신규 보안 공고 {n}건*"
    if cycle_label:
        header += f"  _{cycle_label}_"

    # 정렬: 점수 높은 것 먼저
    items_sorted = sorted(items, key=lambda x: -(x[1].total_score or 0))

    # 최대 10건까지만 (그 이상은 메시지 너무 길어짐)
    SHOW_LIMIT = 10
    shown = items_sorted[:SHOW_LIMIT]
    more = n - SHOW_LIMIT if n > SHOW_LIMIT else 0

    attachments = [_build_attachment(a, s, dashboard_url) for a, s in shown]
    if more > 0:
        attachments.append({
            "color": "#94a3b8",
            "blocks": [{
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"_외 {more}건 더 — <{dashboard_url}|대시보드>에서 전체 확인_",
                },
            }],
        })

    payload = {
        "text": f"신규 보안 공고 {n}건",  # fallback (브라우저 알림용)
        "blocks": [
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": header},
            },
        ],
        "attachments": attachments,
    }

    try:
        r = requests.post(webhook, json=payload, timeout=10)
        r.raise_for_status()
        log.info("slack alert sent: %d건", n)
        return True
    except Exception as e:
        log.error("slack alert 발송 실패: %s", e)
        return False


def _post_webhook(payload: dict) -> bool:
    """범용 Slack webhook POST — 회귀 경보 등 다른 알림에서 재사용."""
    cfg = (settings().get("alert") or {})
    if not cfg.get("slack_enabled", False):
        return False
    webhook = ((secrets().get("slack") or {}).get("webhook_url") or "").strip()
    if not webhook or webhook == "???":
        return False
    try:
        r = requests.post(webhook, json=payload, timeout=10)
        r.raise_for_status()
        return True
    except Exception as e:
        log.error("slack webhook 발송 실패: %s", e)
        return False


def dispatch_pending_alerts() -> bool:
    """매 cron 끝에 호출 — 평일 09~18시 KST 면 alerted_at IS NULL 보안 공고 묶음 발송.

    영업시간 외에는 발송 X (큐에 누적 그대로 둠).
    다음 영업일 09시 첫 cron에 어젯밤+오늘새벽 미발송 신규 모두 한 번에 전달.

    Returns: True = 발송 성공, False = skip (영업시간 외 / 0건 / webhook 미설정)
    """
    now = datetime.now(KST)
    if not _is_business_hours(now):
        log.info("slack alert: 영업시간 외(%s) — 누적만, 발송 skip", now.strftime("%a %H:%M"))
        return False

    # DB에서 alerted_at IS NULL 보안 통과 row + score 모두 가져오기
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT a.id, a.source, a.external_id, a.title, a.url, a.agency,
                              a.posted_at, a.deadline_at, a.budget_mw, a.budget_period,
                              a.matched_keywords_json, a.eligibility_status, a.eligibility_note,
                              s.keyword_score, s.budget_score, s.consortium_score,
                              s.competitor_score, s.trl_score, s.total_score, s.theme_fit
                       FROM announcement a
                       LEFT JOIN score s ON s.announcement_id = a.id
                       WHERE a.is_security = TRUE
                         AND a.alerted_at IS NULL
                         AND a.is_dismissed = FALSE
                       ORDER BY a.posted_at DESC NULLS LAST, s.total_score DESC NULLS LAST"""
                )
                rows = cur.fetchall()
    except Exception:
        log.exception("dispatch_pending_alerts: DB 조회 실패")
        return False

    if not rows:
        log.info("slack alert: 영업시간(%s)이지만 미발송 공고 0건 — skip", now.strftime("%H:%M"))
        return False

    # Announcement / Score 객체 재구성
    items = []
    for r in rows:
        try:
            mk = json.loads(r["matched_keywords_json"] or "[]")
        except Exception:
            mk = []
        a = Announcement(
            source=r["source"], external_id=r["external_id"], title=r["title"],
            url=r["url"], agency=r["agency"], posted_at=r["posted_at"],
            deadline_at=r["deadline_at"], budget_mw=r["budget_mw"],
            budget_period=r["budget_period"], matched_keywords=mk,
            eligibility_status=r["eligibility_status"], eligibility_note=r["eligibility_note"],
            is_security=True,
        )
        s = Score(
            announcement_id=r["id"],
            keyword_score=float(r["keyword_score"] or 0),
            budget_score=float(r["budget_score"] or 0),
            consortium_score=float(r["consortium_score"] or 0),
            competitor_score=float(r["competitor_score"] or 0),
            trl_score=float(r["trl_score"] or 0),
            total_score=float(r["total_score"] or 0),
            theme_fit=float(r["theme_fit"] or 0),
            rationale={},
        )
        items.append((a, s))

    # 영업시간 첫 알림(09시)에는 어젯밤 누적분이라 라벨 다르게
    if now.hour == 9 and len(items) > 5:
        label = f"{now.strftime('%m-%d %H:%M')} · 영업시간 시작 (누적 {len(items)}건)"
    else:
        label = now.strftime("%Y-%m-%d %H:%M")

    sent = notify_new_announcements(items, cycle_label=label)
    if not sent:
        return False

    # 발송 성공 — alerted_at 일괄 UPDATE
    ids = [r["id"] for r in rows]
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE announcement SET alerted_at = NOW() WHERE id = ANY(%s)", (ids,))
        log.info("slack alert: %d건 발송 완료 + alerted_at 표시", len(ids))
    except Exception:
        log.exception("alerted_at UPDATE 실패 (알림은 이미 발송됨)")
    return True
