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
DEFAULT_DASHBOARD_URL = "https://yellowcornsalad.github.io/RFP-Targeter/"

# 영업시간 — 사용자 요청: 평일 09:00 ~ 21:00 KST 만 슬랙 알림
# [2026-05-28] 18 → 21 확대 + notify_crawl_complete 도 영업시간 가드로 통일
# 그 외 시간 들어온 신규 보안 공고는 alerted_at NULL 인 채로 누적 →
# 다음 영업시간 첫 cron(평일 09시)에 묶음 발송
DEFAULT_BIZ_HOUR_START = 9
DEFAULT_BIZ_HOUR_END = 21  # 21시 정각 cron까지 포함, 22시부터 누적


def _is_business_hours(now: datetime | None = None) -> bool:
    """현재 시각이 평일 09:00 ~ 21:00 KST 인지.

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
    # budget_mw 는 백만원 단위 (1억 = 100). 1억 이상은 '억', 미만은 '백만원'.
    # [2026-05-29 버그픽스] 기존 /1000 → /100. (10억을 1억으로 잘못 표기하던 문제)
    if budget_mw is None or budget_mw <= 0:
        return "예산 정보 없음"
    if budget_mw >= 100:
        eok = budget_mw / 100
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


def notify_crawl_complete(stats: list, dispatched_count: int = 0) -> bool:
    """매 크롤 사이클 끝에 '크롤 완료' 알림 발사 — 평일 09~21 KST 영업시간만.

    [2026-05-28 1차] 영업시간 가드 제거 (24/7 발사)
    [2026-05-28 2차] 영업시간 가드 재도입 — dispatch_pending_alerts 와 동일 시간대로 통일.
                    사용자 요청: 새벽/주말 슬랙 노이즈 차단, 평일 09~21만 발사.
                    cron 은 24/7 계속 돌고, 비영업시간엔 슬랙만 침묵.

    stats: list of RunStats (source, new, updated, filtered_in)
    dispatched_count: 이번 사이클 dispatch_pending_alerts 가 발사한 슬랙 알림 건수
    """
    cfg = (settings().get("alert") or {})
    if not cfg.get("slack_enabled", False):
        return False

    # [2026-05-29 사용자 요청] 크롤 완료 메시지 비활성화 (기본 OFF).
    # 신규 공고 알림(dispatch_pending_alerts, 80+ AND 1억+)만 유지하고
    # 매 사이클 완료 요약 노이즈는 제거. settings.alert.crawl_complete_enabled=true 로 재활성.
    if not cfg.get("crawl_complete_enabled", False):
        log.info("slack notify_crawl_complete: 비활성화됨 (alert.crawl_complete_enabled=false) — skip")
        return False

    now_kst = datetime.now(KST)
    if not _is_business_hours(now_kst):
        log.info(
            "slack notify_crawl_complete: 영업시간 외(%s) — 발송 skip",
            now_kst.strftime("%a %H:%M"),
        )
        return False
    header = f"🔄 *[크롤 완료]* {now_kst.strftime('%Y-%m-%d %H:%M KST')}"

    # source별 통계 한 줄로
    parts = []
    total_new, total_sec = 0, 0
    for s in stats:
        if s.error:
            parts.append(f"~{s.source.upper()}~ ❌")
            continue
        parts.append(f"{s.source.upper()} {s.new}/{s.updated}")
        total_new += s.new
        total_sec += s.filtered_in
    stats_line = " · ".join(parts)

    body = (
        f"{header}\n"
        f"`{stats_line}` (new/upd)\n"
        f"신규 보안 통과 *{total_sec}건* · 슬랙 발사 *{dispatched_count}건* (80+ AND 1억+)"
    )
    return _post_webhook({"text": body})


def notify_crawl_failure(stats: list) -> bool:
    """크롤 사이클에서 source 에러가 1건이라도 있으면 Slack 경보.

    [2026-05-29 사용자 요청] 크롤 완료(성공) 메시지는 OFF 하되, '실패'는 알림.
    - 성공만 있는 사이클: 조용 (notify_crawl_complete 비활성)
    - source 에러 1+: 🚨 경보 발사

    영업시간 가드(평일 09~21 KST) — 사용자 슬랙 정책과 통일(새벽/주말 노이즈 차단).
    비영업시간 실패는 지속되면 다음 영업일 09시 cron 에서 잡히고,
    워크플로 자체가 죽는 경우(타임아웃/크래시)는 monitor_crawler.yml 의
    정지 감지(70분 gap)가 별도로 커버한다.
    settings.alert.crawl_failure_enabled=false 로 끌 수 있음(기본 ON).
    """
    cfg = (settings().get("alert") or {})
    if not cfg.get("slack_enabled", False):
        return False
    if not cfg.get("crawl_failure_enabled", True):
        return False

    failed = [s for s in stats if getattr(s, "error", None)]
    if not failed:
        return False  # 실패 없음 → 조용

    now_kst = datetime.now(KST)
    if not _is_business_hours(now_kst):
        log.info(
            "slack notify_crawl_failure: 영업시간 외(%s) — 발송 skip (%d개 소스 실패)",
            now_kst.strftime("%a %H:%M"), len(failed),
        )
        return False

    lines = []
    for s in failed:
        err = (s.error or "").strip().splitlines()[0][:120] if s.error else "알 수 없는 오류"
        lines.append(f"• *{s.source.upper()}* — {err}")
    body = (
        f"🚨 *[크롤 실패]* {now_kst.strftime('%Y-%m-%d %H:%M KST')}\n"
        f"{len(failed)}개 소스 크롤 실패:\n" + "\n".join(lines) + "\n"
        f"_워크플로 전체 정지는 모니터가 별도 감지_"
    )
    return _post_webhook({"text": body})


def notify_daily_heartbeat() -> bool:
    """매일 지정 시각(기본 09시 KST) 첫 크롤 사이클에 '정상 가동' 하트비트 1회.

    [사용자 요청 2026-05-29] 크롤 완료 메시지를 끈 뒤 '살아있다' 신호가
    사라져, 하루 1번 저노이즈 안심 핑을 보냄 (성공/실패 무관 — 가동 자체를 알림).
    - 발송 조건: slack_enabled + daily_heartbeat_enabled(기본 ON) +
      현재 KST 시각 == daily_heartbeat_hour(기본 9) + 오늘 미발송(meta dedup).
    - 내용: 지난 24시간 크롤 N회 · 마지막 동기화 시각 · 실패 건수.
    매시 크롤이 09시대에 여러 번 돌아도 meta(last_heartbeat_date)로 1회만.
    settings.alert.daily_heartbeat_enabled=false 로 끌 수 있음.
    """
    from datetime import timedelta, timezone as _tz

    from rfp_targeter.db.models import meta_get, meta_set

    cfg = (settings().get("alert") or {})
    if not cfg.get("slack_enabled", False):
        return False
    if not cfg.get("daily_heartbeat_enabled", True):
        return False

    now = datetime.now(KST)
    if now.hour != int(cfg.get("daily_heartbeat_hour", 9)):
        return False
    today = now.strftime("%Y-%m-%d")
    since_iso = (now.astimezone(_tz.utc) - timedelta(hours=24)).isoformat(timespec="seconds")

    try:
        with get_conn() as conn:
            if meta_get(conn, "last_heartbeat_date") == today:
                return False  # 오늘 이미 발송
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(DISTINCT LEFT(started_at, 13)) AS cycles, "
                    "COUNT(*) FILTER (WHERE error IS NOT NULL) AS errs, "
                    "MAX(finished_at) AS last "
                    "FROM fetch_log WHERE started_at >= %s",
                    (since_iso,),
                )
                r = cur.fetchone() or {}
            cycles = int(r.get("cycles") or 0)
            errs = int(r.get("errs") or 0)
            last = r.get("last")
    except Exception:
        log.exception("heartbeat: DB 조회 실패 — skip")
        return False

    last_txt = ""
    if last:
        try:
            last_txt = datetime.fromisoformat(last).astimezone(KST).strftime("%m-%d %H:%M")
        except Exception:
            pass

    icon = "✅" if errs == 0 else "⚠️"
    dash = cfg.get("dashboard_url") or DEFAULT_DASHBOARD_URL
    body = (
        f"{icon} *[크롤 상태 점검]* 지난 24시간 *{cycles}회* 자동 수집"
        + (f" · 실패 *{errs}건*" if errs else " · 실패 0건")
        + (f"\n마지막 동기화: *{last_txt} KST*" if last_txt else "")
        + f"\n<{dash}|대시보드 열기>"
    )
    sent = _post_webhook({"text": body})
    if sent:
        try:
            with get_conn() as conn:
                meta_set(conn, "last_heartbeat_date", today)
        except Exception:
            log.exception("heartbeat: meta_set 실패 (드물게 중복 발송 가능)")
    return sent


def dispatch_pending_alerts() -> bool:
    """매 cron 끝에 호출 — 평일 09~21시 KST 면 alerted_at IS NULL 보안 공고 묶음 발송.

    영업시간 외에는 발송 X (큐에 누적 그대로 둠).
    다음 영업일 09시 첫 cron에 어젯밤+오늘새벽 미발송 신규 모두 한 번에 전달.

    Returns: True = 발송 성공, False = skip (영업시간 외 / 0건 / webhook 미설정)
    """
    now = datetime.now(KST)
    if not _is_business_hours(now):
        log.info("slack alert: 영업시간 외(%s) — 누적만, 발송 skip", now.strftime("%a %H:%M"))
        return False

    # DB에서 alerted_at IS NULL 보안 통과 row + score 가져오기
    # ⚠️ 발송 규칙 [2026-06-01 사용자 결정 — '점수 80' → '적합성' 기준 교체]:
    #   1) 🤖 LLM 도메인 적합성 = high (명확히 본업 관련) 만. [2026-06-01 재조정]
    #      medium 은 곁가지(예: AX 바우처 — 엔키가 '수요기업'으로 활용 여지뿐, 본업 무관)
    #      까지 잡혀 푸시 과다 → medium 은 대시보드에서만 확인, 슬랙은 high 만.
    #   2) budget_mw ≥ 100 (= 1억 이상). NULL은 제외 (엄격)
    #   3) 활성 공고 (마감 미래 + 최근 60일 내 등록 마감미명시)
    # (이전 '종합점수 ≥ 80' 은 LLM 배율 후 점수가 80에 거의 안 닿아 무알림 → 폐기)
    # 적합성은 llm_assess_json(JSON TEXT)이라 SQL 캐스트 에러 회피 위해 Python 에서 필터.
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT a.id, a.source, a.external_id, a.title, a.url, a.agency,
                              a.posted_at, a.deadline_at, a.budget_mw, a.budget_period,
                              a.matched_keywords_json, a.eligibility_status, a.eligibility_note,
                              a.llm_assess_json,
                              s.keyword_score, s.budget_score, s.consortium_score,
                              s.competitor_score, s.trl_score, s.total_score, s.theme_fit
                       FROM announcement a
                       LEFT JOIN score s ON s.announcement_id = a.id
                       WHERE a.is_security = TRUE
                         AND a.alerted_at IS NULL
                         AND a.is_dismissed = FALSE
                         AND a.source IN ('iitp','kisa','krit','nipa','mss','koica')
                         AND a.budget_mw IS NOT NULL AND a.budget_mw >= 100
                         AND (
                           a.deadline_at >= CURRENT_DATE::text
                           OR (a.deadline_at IS NULL
                               AND a.posted_at >= (CURRENT_DATE - 60)::text)
                         )
                       ORDER BY a.posted_at DESC NULLS LAST, s.total_score DESC NULLS LAST"""
                )
                rows = cur.fetchall()
    except Exception:
        log.exception("dispatch_pending_alerts: DB 조회 실패")
        return False

    # 🤖 [2026-07-03 버그픽스] 홈페이지 노출 게이트와 동일 기준으로 발송.
    #   이전엔 relevance=high 만 봐서, 시상·공지·인력모집(doc_type)이 high 면
    #   슬랙으로 나갔다(홈페이지엔 biddable/doc_type 게이트로 안 보이는데 슬랙만 뜸).
    #   조건: ① relevance=high  ② biddable != false  ③ doc_type 시상·인력·행사·공지 제외
    #        (단 수요/공급/참여기업·사업자 모집은 회사 참여 여지 있어 예외)
    _ALERT_REL = {"high"}
    _NOISE_DT = {"award", "hr", "event", "notice"}
    filtered = []
    for r in rows:
        try:
            j = json.loads(r.get("llm_assess_json") or "{}") or {}
        except Exception:
            j = {}
        rel, dt, bd = j.get("relevance"), j.get("doc_type"), j.get("biddable")
        if rel not in _ALERT_REL:
            continue
        if bd is False:                    # 응찰 불가(물품구매·성과분석 등)
            continue
        if dt in _NOISE_DT:                # 시상·인력·행사·공지
            title = r.get("title") or ""
            if not any(k in title for k in ("수요기업", "공급기업", "참여기업", "사업자 모집")):
                continue
        filtered.append(r)
    rows = filtered

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
