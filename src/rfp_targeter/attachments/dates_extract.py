"""본문/첨부에서 마감일 + 신청 시작일 추출.

다양한 한글 표현 지원:
  접수마감 / 신청마감 / 제출마감 / 마감일 / 응찰기한 / 입찰참여기한 /
  참가신청기한 / 모집기한 / 공모기한 / 접수기간 / 신청기간 / 공모기간

KISA/NIPA/KOSA/IITP 어댑터가 fetch_detail 끝에 호출.
MSS 는 OpenAPI 응답에 직접 필드 있어서 호출 불필요.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Optional


# 마감일 단독 표현 (시작~끝 범위 없음, 마감만)
_DEADLINE_LABELS = (
    r"(?:접수\s*마감|신청\s*마감|마감일시|마감\s*일|제출\s*마감|응찰\s*기한|"
    r"제출\s*기한|입찰\s*마감|입찰\s*참여\s*기한|참가\s*신청\s*기한|"
    r"모집\s*기한|공모\s*기한|접수\s*기한|신청\s*기한|마감)"
)

# 신청 시작/끝 범위 라벨
_RANGE_LABELS = (
    r"(?:접수\s*기간|신청\s*기간|공모\s*기간|입찰\s*기간|모집\s*기간|제출\s*기간|"
    r"접수|신청|공모|모집|제출|입찰)"
)

# 날짜 한 개 — YYYY.MM.DD / YYYY-MM-DD / YYYY/MM/DD / YYYY년 MM월 DD일
_DATE = r"(\d{4})\s*[.\-/년]\s*(\d{1,2})\s*[.\-/월]\s*(\d{1,2})\s*일?"

_RE_DEADLINE = re.compile(
    rf"{_DEADLINE_LABELS}[^\d]{{0,30}}{_DATE}",
    re.IGNORECASE,
)

# 범위 패턴 — "YYYY.MM.DD ~ YYYY.MM.DD" 또는 "YYYY.MM.DD HH:MM ~ YYYY.MM.DD HH:MM"
# NIPA: "신청기간 : 2026-05-18 09:51 ~ 2026-06-12 15:00"
# 시간 부분(HH:MM 또는 HH시 MM분)은 옵션. 라벨 다음 ':' 또는 '-' 도 허용.
_TIME_OPT = r"(?:\s+\d{1,2}\s*[:시：]\s*\d{1,2}\s*분?)?"
_RE_RANGE = re.compile(
    rf"{_RANGE_LABELS}\s*[:：\-]?\s*[^\d]{{0,20}}{_DATE}"
    rf"{_TIME_OPT}"
    rf"\s*[~∼\-––]\s*"
    rf"(?:(\d{{4}})\s*[.\-/년]\s*)?(\d{{1,2}})\s*[.\-/월]\s*(\d{{1,2}})\s*일?"
    rf"{_TIME_OPT}",
    re.IGNORECASE,
)

# 일반 범위 (라벨 없이 두 날짜만 — 보조 신호) + 시간 옵션
_RE_BARE_RANGE = re.compile(
    rf"{_DATE}{_TIME_OPT}\s*[~∼\-––]\s*"
    rf"(?:(\d{{4}})\s*[.\-/년]\s*)?(\d{{1,2}})\s*[.\-/월]\s*(\d{{1,2}})\s*일?"
    rf"{_TIME_OPT}"
)


def _to_iso(y: int, m: int, d: int) -> Optional[str]:
    """(y,m,d) → 'YYYY-MM-DD' (유효성 검증). 비현실적이면 None."""
    if not (2020 <= y <= 2030 and 1 <= m <= 12 and 1 <= d <= 31):
        return None
    try:
        return date(y, m, d).isoformat()
    except ValueError:
        return None


def extract_dates(body: str) -> tuple[Optional[str], Optional[str]]:
    """본문에서 (application_start_date, deadline_at) 추출.

    우선순위:
      1. "접수기간/공모기간 YYYY.MM.DD ~ YYYY.MM.DD" 범위 — start, end 둘 다 OK
      2. "접수마감 YYYY.MM.DD" 단독 — deadline 만
      3. 라벨 없는 범위 (YYYY.MM.DD ~ MM.DD) — 보조 신호로 start, end

    Returns: (start_iso, deadline_iso) — 못 찾으면 None
    """
    if not body or not isinstance(body, str):
        return None, None

    start_iso, deadline_iso = None, None

    # 1) 범위 (start ~ end) — 가장 풍부한 신호
    m = _RE_RANGE.search(body)
    if m:
        y1, mo1, d1 = int(m.group(1)), int(m.group(2)), int(m.group(3))
        y2_raw, mo2, d2 = m.group(4), int(m.group(5)), int(m.group(6))
        y2 = int(y2_raw) if y2_raw else y1  # end 의 연도가 없으면 start 연도 재사용
        s = _to_iso(y1, mo1, d1)
        e = _to_iso(y2, mo2, d2)
        if s and e and s <= e:
            start_iso, deadline_iso = s, e

    # 2) 마감일 단독 (deadline 만 없으면 추가)
    if not deadline_iso:
        m = _RE_DEADLINE.search(body)
        if m:
            y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
            iso = _to_iso(y, mo, d)
            if iso:
                deadline_iso = iso

    # 3) 라벨 없는 범위 (보조)
    if not start_iso and not deadline_iso:
        m = _RE_BARE_RANGE.search(body)
        if m:
            y1, mo1, d1 = int(m.group(1)), int(m.group(2)), int(m.group(3))
            y2_raw, mo2, d2 = m.group(4), int(m.group(5)), int(m.group(6))
            y2 = int(y2_raw) if y2_raw else y1
            s = _to_iso(y1, mo1, d1)
            e = _to_iso(y2, mo2, d2)
            # 보수적: 라벨 없으니 둘 다 합리적 범위일 때만 (start ≤ end, end 가 오늘 이후 또는 60일 내)
            if s and e and s <= e:
                today = date.today().isoformat()
                gap = (date(y2, mo2, d2) - date.today()).days
                if -60 <= gap <= 365:  # 너무 과거/먼 미래 X
                    start_iso, deadline_iso = s, e

    return start_iso, deadline_iso
