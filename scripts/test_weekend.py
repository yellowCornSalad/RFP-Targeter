"""주말 슬랙 차단 검증 — 토/일/평일 시각으로 영업시간 판정."""
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

sys.path.insert(0, "src")
from rfp_targeter.notifier.slack import _is_business_hours

KST = ZoneInfo("Asia/Seoul")
cases = [
    ("금 10시", datetime(2026, 7, 3, 10, 0, tzinfo=KST)),
    ("토 10시", datetime(2026, 7, 4, 10, 0, tzinfo=KST)),
    ("일 10시", datetime(2026, 7, 5, 10, 0, tzinfo=KST)),
    ("월 09시", datetime(2026, 7, 6, 9, 0, tzinfo=KST)),
    ("토 09시(하트비트 시각)", datetime(2026, 7, 4, 9, 0, tzinfo=KST)),
]
print("_is_business_hours (모든 슬랙 발송이 이걸 체크):")
for label, dt in cases:
    biz = _is_business_hours(dt)
    print(f"  {label:22s} weekday={dt.weekday()} → 발송={'O' if biz else 'X (차단)'}")

# 하트비트 주말 로직 (weekday >= 5 → 차단)
print("\n하트비트 주말 가드:")
for label, dt in cases:
    blocked = dt.weekday() >= 5
    print(f"  {label:22s} → {'X 차단(주말)' if blocked else 'O 평일 통과'}")
