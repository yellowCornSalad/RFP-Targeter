"""슬랙 webhook 셋업 검증 — 가짜 공고 1건으로 알림 발송.

먼저 config/secrets.yaml 의 slack.webhook_url 채워두고:
    python scripts/test_slack.py

성공 시 슬랙 채널에 샘플 카드 1건 도착.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

from rfp_targeter.db.models import Announcement, Score  # noqa: E402
from rfp_targeter.notifier.slack import notify_new_announcements  # noqa: E402


def main():
    a = Announcement(
        source="kisa",
        external_id="TEST-001",
        title="2026년 양자내성암호 시범전환 지원사업 참가기업 모집 [테스트]",
        url="https://www.kisa.or.kr/403/form?postSeq=10000",
        agency="정보보호기획과",
        posted_at="2026-05-21",
        deadline_at="2026-06-05",
        budget_mw=2800,
        summary="테스트 알림 — 슬랙 webhook 정상 작동 확인용",
        matched_keywords=["정보보호", "양자내성암호", "PQC", "암호", "인증"],
        is_security=True,
    )
    s = Score(
        announcement_id=a.id,
        keyword_score=86,
        budget_score=100,
        consortium_score=90,
        competitor_score=80,
        trl_score=45,
        total_score=99,
        theme_fit=93,
        rationale={},
    )

    print("슬랙으로 테스트 알림 발송 시도...")
    ok = notify_new_announcements([(a, s)], cycle_label="테스트")
    if ok:
        print("✅ 발송 성공 — 슬랙 채널 확인")
    else:
        print("❌ 발송 실패 또는 skip")
        print("   - secrets.yaml 의 slack.webhook_url 확인")
        print("   - settings.yaml 의 alert.slack_enabled = true 확인")


if __name__ == "__main__":
    main()
