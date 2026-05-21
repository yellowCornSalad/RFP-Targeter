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
from typing import Iterable

import requests

from rfp_targeter.config import secrets, settings
from rfp_targeter.db.models import Announcement, Score

log = logging.getLogger(__name__)

# 대시보드 base URL (settings.yaml에 override 가능)
DEFAULT_DASHBOARD_URL = "http://localhost:8501"


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
