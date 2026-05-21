"""공고 본문에서 예산(사업비) + 기간 추출 — 모든 크롤러 공통.

설계 원칙 (hallucination 절대 금지):
- 본문에 명시된 값만 추출. 합산·추정·근사 X
- 신뢰도 낮으면 None 반환 (가짜 값 절대 안 넣음)
- 추출 결과에 항상 원문 발췌(raw_excerpt) 첨부 — 사용자가 검증 가능

지원 패턴:
A. 명시적 prefix (HIGH 신뢰):
   "사업비 2,800백만원", "총사업비 1.5억원", "정부출연금 4.4억원"
   "연구비 76억", "과제당 4.6억원", "지원규모 200억원"
   "예산액 70,000,000원", "소요예산 48,000,000원"
B. 연도 동반 (MEDIUM-HIGH):
   "'26년 20억원", "2026년 50억원", "1차년도 75백만원"
C. 단위 동반 기간 (HIGH):
   "총 연구기간 36개월 / 900백만원", "연 5억원", "과제당 연 3억원"
D. 표 셀 / 꺾쇠 (MEDIUM):
   "<60백만원>", "│75백만원│"

제외 패턴 (반드시 None):
- 참가비, 수강료, 할인, 정가, 광고, 상금, 시상
- "이상", "미만", "초과" 단순 기준치
- 연도 (\d년)
- 페이지 번호

사용:
    info = extract_budget_info(body_text)  # → BudgetInfo | None
    if info:
        # info.mw : 백만원 단위 (검증된 값)
        # info.period_label : "연간" | "총사업비" | "5년 총" | "1차년도 6개월" 등
        # info.raw_excerpt : 본문 발췌 원문 (UI 표시용, hallucination 검증)
        # info.confidence : "high" | "medium"
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

# ─────────────────────────────────────────────────────────────────────────────
# 1) prefix — "사업비"류 명시 키워드 (HIGH 신뢰)
# ─────────────────────────────────────────────────────────────────────────────
_PREFIX_HIGH = (
    r"(?:총\s*)?(?:"
    r"사업\s*비|사업\s*규모|"
    r"연구\s*비|총\s*연구\s*비|연구\s*개발\s*비|정부\s*지원\s*연구\s*개발\s*비|"
    r"예\s*산\s*액|소\s*요\s*예\s*산|총\s*예\s*산|연구\s*개발\s*예\s*산|예\s*산|"
    r"정부\s*출연금|출\s*연금|"
    r"지원\s*금액|지원\s*규모|지원\s*예산|지원\s*한도|"
    r"투자\s*규모|"
    r"과제\s*당|과제별|과제\s*당\s*연구\s*비|"
    r"연구\s*단\s*당|연구단당\s*연구\s*비|"
    r"총\s*투자|총\s*사업|"
    r"사업\s*기간|연구\s*기간|총\s*연구\s*기간|총\s*사업\s*기간|"
    r"\d\s*차\s*년도|"
    r"연구\s*개발\s*기간"
    r")"
)

# ─────────────────────────────────────────────────────────────────────────────
# 2) 숫자 + 단위
# ─────────────────────────────────────────────────────────────────────────────
_NUM = r"(\d[\d,]*(?:\.\d+)?)"

# 화폐 단위만 (`년`/`개월`/`%` 등 제외)
_UNIT_MONEY = (
    r"("
    r"억\s*원|억\b|"           # 억원, 억
    r"백\s*만\s*원|"           # 백만원
    r"천\s*만\s*원|"           # 천만원
    r"만\s*원|"                # 만원
    r"천\s*원|"                # 천원
    r"원\b|"                   # 원 (단독, 끝)
    r"won|krw"                 # 영문
    r")"
)

# ─────────────────────────────────────────────────────────────────────────────
# 3) 제외 키워드 (이 단어가 prefix 주변에 있으면 매칭 무시)
# ─────────────────────────────────────────────────────────────────────────────
_EXCLUDE_WORDS = re.compile(
    r"참가\s*비|수강\s*료|할인|정\s*가|광고|상\s*금|시상|회비|판\s*가|"
    r"등록\s*비|연회\s*비|입장\s*료|기탁\s*금|예치\s*금|보증\s*금|"
    r"매출액|매출\s*규모|매출\s*기준|"
    r"인건\s*비|급여|봉급|장학금|"  # 인건비 단가
    r"미만|이상|초과|이하(?:로|의)?\s*\d"  # "5억원 이상" 같은 기준치
)

# 단가 (개당 가격, 월급 등) — 이게 매칭 직전에 있으면 단가 단위로 인식해 제외
_UNIT_PRICE_PREFIX = re.compile(
    r"월\s*$|"            # "월 150만원" 처럼 unit 직전 "월"
    r"1\s*인\s*당\s*$|"    # "1인당 30만원"
    r"개\s*당\s*$|"
    r"건\s*당\s*$|"
    r"명\s*당\s*$|"
    r"인\s*당\s*$|"
    r"시간\s*당\s*$|"
    r"일\s*당\s*$"
)

# ─────────────────────────────────────────────────────────────────────────────
# 4) 기간 — "연간" / "N년" / "N개월" / 차년도
# ─────────────────────────────────────────────────────────────────────────────
_PERIOD_YEAR_LABEL = re.compile(
    r"['‘’‛ʼ`＇]?(\d{2,4})\s*년"  # '26년, '26년, 2026년 (다양한 typographic apostrophe)
)
# 사업기간 prefix 패턴 — 가운데 텍스트 80자 허용 (날짜 범위/약/등 흡수)
# 그러나 prefix와 N(개월|년) 사이에 다른 사업기간 표현이 또 나오면 안 됨 (greedy 방지)
_PERIOD_DURATION = re.compile(
    r"(?:총\s*)?(?:사업\s*기간|연구\s*기간|총\s*연구\s*기간|수행\s*기간|총\s*사업\s*기간|"
    r"연구\s*개발\s*기간|전체\s*사업\s*기간|총\s*기간|지원\s*기간|협약\s*기간|계약\s*기간)"
    r"[^()\n]{0,80}?(?:\(\s*약?\s*)?(\d{1,3})\s*(개월|년)\b"
)
# "X년 Y개월" 형식 별도 (총 사업기간 3년 9개월)
_PERIOD_YEARMONTH = re.compile(
    r"(?:사업\s*기간|연구\s*기간|총\s*사업\s*기간|총\s*연구\s*기간|지원\s*기간|총\s*기간)"
    r"[^()\n]{0,80}?\(?\s*(\d{1,2})\s*년\s*(\d{1,2})\s*개월\s*\)?"
)
# 단독 "(N개월)" / "(약 N개월)" — 본문에 명시
_PERIOD_PAREN_MONTHS = re.compile(
    r"\(\s*(?:약\s*)?(\d{1,3})\s*개월\s*\)|"
    r"\(\s*(\d{1,2})\s*년\s*(\d{1,2})?\s*개월?\s*\)"
)
# 단독 기간 표현 — 년 또는 개월
_DURATION_STANDALONE = re.compile(
    r"\(\s*(\d{1,2})\s*년\s*간?\s*\)|"           # (5년) (5년간) → group 1
    r"(\d{1,2})\s*개\s*년\s*사업|"                # 5개년 사업 → group 2
    r"총\s*(\d{1,2})\s*년\s*간?(?:\s|$|[,.])|"   # 총 5년 → group 3
    r"(\d{1,2})\s*년\s*간(?:\s|$|[,.])"           # 5년간 → group 4
)
# 개월 단위 기간 (별도 — _find_duration_in 에서 이 결과만 따로 처리)
_DURATION_MONTHS_STANDALONE = re.compile(
    r"(\d{1,3})\s*개월\s*(?:사업|간|동안|이내)|"  # 60개월 사업 / 36개월 간
    r"총\s*(\d{1,3})\s*개월"                      # 총 36개월
)
# 연도 범위 — 모든 따옴표 문자 포함: ' ’ ‘ ` ' " ＇
# 정부 공고 본문에 자주 나오는 typographic apostrophe: U+2019 ('), U+2018 (‘), U+0027 (')
_QUOTE_CHARS = r"['‘’‛ʼ`＇]?"
_RANGE_YEARS = re.compile(
    rf"{_QUOTE_CHARS}(\d{{2,4}})\s*년\s*~\s*{_QUOTE_CHARS}(\d{{2,4}})\s*년"
)
_PERIOD_CHAJEONDO = re.compile(r"(\d)\s*차\s*년도")
_PERIOD_ANNUAL = re.compile(r"연\s*간|연\s*\d|/\s*년\b|당\s*연\b")


# ─────────────────────────────────────────────────────────────────────────────
# 5) 메인 매칭 — prefix 다음에 (year/period 옵션) + 금액 + 단위
# ─────────────────────────────────────────────────────────────────────────────
# Group structure:
#   1: prefix label
#   2: optional year (e.g. '26')
#   3: amount number
#   4: money unit
_PATTERN_PREFIXED = re.compile(
    _PREFIX_HIGH +                              # prefix (non-capturing)
    r"(?P<gap>.{0,80}?)"                        # 임의 텍스트 80자 (lazy) — 숫자(연도) 허용
    + _NUM +                                    # group 2: amount
    r"\s*" +
    _UNIT_MONEY                                 # group 3: unit
    , re.IGNORECASE | re.DOTALL,
)

# 표 셀 / 꺾쇠 패턴 (prefix 없을 때) — "<60백만원>", "│75백만원│", "(900백만원)"
_PATTERN_CELL = re.compile(
    r"[<\[│|(（〈⟨]\s*" + _NUM + r"\s*" + _UNIT_MONEY + r"\s*[>\]│|)）〉⟩]"
)

# 연도 + 금액 (prefix 없이) — "'26년 20억원", "2026년 50억원"
_PATTERN_YEAR_AMOUNT = re.compile(
    r"['‘’‛ʼ`＇]?(\d{2,4})\s*년\s*"     # group 1: year (다양한 apostrophe)
    + _NUM +                              # group 2: amount
    r"\s*" + _UNIT_MONEY +                # group 3: unit
    r"(?:\s*(내외|이내|규모|수준))?"
)


# ─────────────────────────────────────────────────────────────────────────────
# 데이터 클래스
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class BudgetInfo:
    mw: int                    # 백만원 단위
    period_label: str          # "연간" | "총사업비" | "단년" | "1차년도 6개월" | "다년차 합" 등
    raw_excerpt: str           # 본문 발췌 — hallucination 방지
    confidence: str            # "high" | "medium"
    duration_months: int | None = None  # 사업기간 (개월), 추출 가능 시
    years_covered: int | None = None    # 몇 년치인지 (총 사업비 / 연간 식별용)


# ─────────────────────────────────────────────────────────────────────────────
# Helper
# ─────────────────────────────────────────────────────────────────────────────
def _unit_to_mw(num_str: str, unit_raw: str) -> int | None:
    """숫자+단위 → 백만원 단위. 비현실 값 None."""
    try:
        n = float(num_str.replace(",", ""))
    except ValueError:
        return None
    if n <= 0:
        return None

    u = re.sub(r"\s+", "", unit_raw).lower()
    if u in ("억원", "억"):
        mw = n * 100
    elif u == "백만원":
        mw = n
    elif u == "천만원":
        mw = n * 10
    elif u == "만원":
        mw = n / 100
    elif u == "천원":
        mw = n / 100_000
    elif u in ("원", "won", "krw"):
        mw = n / 1_000_000
    else:
        return None

    mw_int = int(round(mw))
    # 비현실 필터: 1백만 미만 → 단가/할인가, 1조 초과 → 부처 통합 누계
    if mw_int < 1 or mw_int > 1_000_000:
        return None
    return mw_int


def _has_exclude_word(snippet: str) -> bool:
    """제외 키워드(참가비 등) 가 매칭 주변에 있는지."""
    return _EXCLUDE_WORDS.search(snippet) is not None


def _normalize_year(y: int) -> int:
    """2자리 연도면 2000+ 보정."""
    if y < 100:
        return 2000 + y
    return y


def _find_duration_in(text_block: str) -> tuple[int | None, int | None]:
    """텍스트 블록에서 사업기간 추출. Returns (duration_months, years)."""
    # 1. "사업기간 ... 3년 9개월" (혼합 표현)
    m = _PERIOD_YEARMONTH.search(text_block)
    if m:
        y = int(m.group(1))
        mo = int(m.group(2))
        if 0 <= y <= 30 and 0 <= mo < 12:
            total = y * 12 + mo
            return total, y if mo == 0 else y + (1 if mo >= 6 else 0)
    # 2. "사업기간 ... N개월" / "사업기간 ... N년"
    m = _PERIOD_DURATION.search(text_block)
    if m:
        n = int(m.group(1))
        if m.group(2) == "년":
            return n * 12, n
        else:
            return n, max(1, round(n / 12))
    # 3. 년 단위 단독 표현 — "(5년간)", "5개년 사업"
    m = _DURATION_STANDALONE.search(text_block)
    if m:
        val = m.group(1) or m.group(2) or m.group(3) or m.group(4)
        if val:
            n = int(val)
            if 1 <= n <= 30:
                return n * 12, n
    # 4. 개월 단위 단독 표현 — "60개월 사업", "(약 9개월)"
    m = _DURATION_MONTHS_STANDALONE.search(text_block)
    if m:
        val = m.group(1) or m.group(2)
        if val:
            months = int(val)
            if 1 <= months <= 360:
                return months, max(1, round(months / 12))
    # 5. 괄호 안의 (N개월) — 본문에 명시 단독
    m = _PERIOD_PAREN_MONTHS.search(text_block)
    if m:
        if m.group(1):
            months = int(m.group(1))
            if 1 <= months <= 360:
                return months, max(1, round(months / 12))
        elif m.group(2):
            y = int(m.group(2))
            mo = int(m.group(3) or 0)
            total = y * 12 + mo
            if 1 <= total <= 360:
                return total, max(1, y + (1 if mo >= 6 else 0))
    # 6. 연도 범위 "'26년~'30년"
    m = _RANGE_YEARS.search(text_block)
    if m:
        y1 = _normalize_year(int(m.group(1)))
        y2 = _normalize_year(int(m.group(2)))
        n_years = y2 - y1 + 1
        if 1 <= n_years <= 30:
            return n_years * 12, n_years
    return None, None


def _detect_period(text: str, amount_start: int, amount_end: int) -> tuple[str, int | None, int | None]:
    """금액 위치 기반 정밀 기간 분석.

    우선순위 (amount 직전 ±25자 = 가장 신뢰):
        1. "연 X" / "연간 X" / "/년 X" → "연간" (+ 전체 사업기간 동반 시 "연간 / 5년 사업")
        2. "총 X" (총사업비) → 사업기간 동반 시 "총 5년간 (26~30)"
        3. "N차년도 X" → "N차년도"
        4. "'26년 X" → "26년분 (5년 사업 26~30)" 또는 "2026년분"
        5. "과제당 X" / "과제별 X" → "과제당"

    그 외 (직전 prefix 없음):
        6. 컨텍스트(±80자)에서 사업기간 추출
        7. 연도 라벨
        8. fallback: "기간 미명시"

    Returns (period_label, duration_months, years_covered).
    """
    # 직전 25자 (immediate context — 가장 신뢰할 만한 라벨)
    immediate = text[max(0, amount_start - 25):amount_start]
    # 넓은 컨텍스트 (사업기간/범위 탐색용)
    wider = text[max(0, amount_start - 200):amount_end + 100]

    # ── 1. 연간 ───────────────────────────────────────────────────
    if re.search(r"연\s*간\s*$|(?:^|[\s/])연\s*$|/\s*년\s*$|당\s*연\s*$", immediate):
        dm, yrs = _find_duration_in(wider)
        if dm:
            return f"연간 / {yrs}년 사업" if yrs else f"연간 / {dm}개월 사업", dm, yrs
        return "연간", None, None

    # ── 2. 총 X (총사업비) ────────────────────────────────────────
    # 직전 25자 안에 "총" 또는 "총사업비/연구비/예산/투자" 명시 → 총사업비
    is_total = (
        re.search(r"(?:^|[\s,(:])총\s*$", immediate)
        or re.search(r"총\s*(?:사업\s*비|연구\s*비|예\s*산|투자)", immediate)
    )
    if is_total:
        dm, yrs = _find_duration_in(wider)
        # 범위 별도 추출 (연도 표시용)
        m_range = _RANGE_YEARS.search(wider)
        if m_range:
            y1 = _normalize_year(int(m_range.group(1)))
            y2 = _normalize_year(int(m_range.group(2)))
            n_yrs = y2 - y1 + 1
            if 1 <= n_yrs <= 30:
                return f"총 {n_yrs}년 ({y1}~{y2})", n_yrs * 12, n_yrs
        # 12개월 미만이면 개월 단위로 표시 (9개월을 "1년"이라 부르면 부정확)
        if dm and dm < 12:
            return f"총 {dm}개월간", dm, None
        if dm and dm % 12 != 0:
            # 비정수 년 (예: 45개월=3년9개월) → "3년 9개월"
            y_part = dm // 12
            m_part = dm % 12
            return f"총 {y_part}년 {m_part}개월", dm, yrs
        if yrs:
            return f"총 {yrs}년간", dm, yrs
        if dm:
            return f"총 {dm}개월간", dm, None
        return "총사업비 (기간 미명시)", None, None

    # ── 3. N차년도 ───────────────────────────────────────────────
    m_cha = re.search(r"(\d)\s*차\s*년도\s*$", immediate)
    if m_cha:
        n_cha = m_cha.group(1)
        dm, yrs = _find_duration_in(wider)
        if yrs:
            return f"{n_cha}차년도 (총 {yrs}년 사업)", dm, yrs
        return f"{n_cha}차년도", dm, yrs

    # ── 4. 연도 라벨 ('26년 또는 2026년) ─────────────────────────
    m_year = re.search(r"['‘’‛ʼ`＇]?(\d{2,4})\s*년\s*$", immediate)
    if m_year:
        y = _normalize_year(int(m_year.group(1)))
        # 같은 컨텍스트에 연도 범위 있으면 → "26년분 (5년 사업 26~30)"
        m_range = _RANGE_YEARS.search(wider)
        if m_range:
            y1 = _normalize_year(int(m_range.group(1)))
            y2 = _normalize_year(int(m_range.group(2)))
            n_yrs = y2 - y1 + 1
            if 1 <= n_yrs <= 30:
                return f"{y}년분 (총 {n_yrs}년 사업 {y1}~{y2})", n_yrs * 12, n_yrs
        return f"{y}년분", None, 1

    # ── 5. 과제당 ────────────────────────────────────────────────
    if re.search(r"과제\s*당\s*$|과제\s*별\s*$|과제\s*당\s*연\s*$", immediate):
        dm, yrs = _find_duration_in(wider)
        if yrs:
            return f"과제당 / 총 {yrs}년", dm, yrs
        return "과제당", dm, yrs

    # ── 6. 넓은 컨텍스트에서 사업기간 ─────────────────────────────
    dm, yrs = _find_duration_in(wider)
    if dm and yrs:
        return f"총 {yrs}년간", dm, yrs
    if dm:
        return f"총 {dm}개월", dm, None

    # ── 7. 연도 라벨 (넓은 컨텍스트) ─────────────────────────────
    m_year = _PERIOD_YEAR_LABEL.search(wider)
    if m_year:
        y = _normalize_year(int(m_year.group(1)))
        return f"{y}년분", None, 1

    # ── 8. fallback ──────────────────────────────────────────────
    return "기간 미명시", None, None


def _excerpt(text: str, start: int, end: int, pad: int = 40) -> str:
    """본문 발췌 — 매칭 주변 ±pad자, 공백 정리."""
    s = max(0, start - pad)
    e = min(len(text), end + pad)
    raw = text[s:e]
    raw = re.sub(r"\s+", " ", raw).strip()
    # 너무 길면 자르기
    if len(raw) > 200:
        raw = raw[:200] + "…"
    return raw


# ─────────────────────────────────────────────────────────────────────────────
# 메인 추출
# ─────────────────────────────────────────────────────────────────────────────
def extract_budget_info(text: str | None) -> BudgetInfo | None:
    """본문에서 예산 + 기간 정보 추출.

    hallucination 절대 금지:
    - 본문에 명시된 값만 반환
    - 못 찾으면 None (가짜 값 X)
    - 결과에 항상 raw_excerpt 첨부 → UI에서 출처 표시

    Returns:
        BudgetInfo | None
    """
    if not text:
        return None

    candidates: list[tuple[int, BudgetInfo]] = []

    # ── A. prefix 동반 ───────────────────────────────────────────────
    for m in _PATTERN_PREFIXED.finditer(text):
        num_str = m.group(2)
        unit = m.group(3)

        # 제외 키워드 가까이 있으면 skip (특히 prefix 직전 30자 내)
        nearby = text[max(0, m.start() - 30):m.start() + 30]
        if _has_exclude_word(nearby):
            continue

        # 숫자 직전 텍스트가 단가 표현(월·1인당·개당 등)이면 skip — 인건비/단가는 사업비 아님
        num_start = m.start(2)
        before_num = text[max(0, num_start - 15):num_start]
        if _UNIT_PRICE_PREFIX.search(before_num):
            continue

        mw = _unit_to_mw(num_str, unit)
        if mw is None:
            continue

        # 금액 위치 기반 정밀 period 분석
        period_label, duration_months, years = _detect_period(
            text, num_start, m.end(3),
        )
        excerpt = _excerpt(text, m.start(), m.end())

        candidates.append((m.start(), BudgetInfo(
            mw=mw,
            period_label=period_label,
            raw_excerpt=excerpt,
            confidence="high",
            duration_months=duration_months,
            years_covered=years,
        )))

    if candidates:
        # 본문 처음에 나오는 게 일반적으로 가장 권위 있음
        candidates.sort(key=lambda x: x[0])
        return candidates[0][1]

    # ── B. 연도 동반 (prefix 없을 때) ────────────────────────────────
    for m in _PATTERN_YEAR_AMOUNT.finditer(text):
        year_str = m.group(1)
        num_str = m.group(2)
        unit = m.group(3)
        # 연도 자체가 이상하면 skip
        try:
            y = int(year_str)
            if y < 20 or (y > 50 and y < 2020) or y > 2099:
                continue
        except ValueError:
            continue

        nearby = text[max(0, m.start() - 30):m.start() + 30]
        if _has_exclude_word(nearby):
            continue

        mw = _unit_to_mw(num_str, unit)
        if mw is None:
            continue

        period_label, duration_months, years = _detect_period(text, m.start(2), m.end(2))

        excerpt = _excerpt(text, m.start(), m.end())

        candidates.append((m.start(), BudgetInfo(
            mw=mw,
            period_label=period_label,
            raw_excerpt=excerpt,
            confidence="medium",
            duration_months=duration_months,
            years_covered=years or 1,
        )))

    if candidates:
        candidates.sort(key=lambda x: x[0])
        return candidates[0][1]

    # ── C. 표 셀 패턴 (prefix 없을 때) ────────────────────────────────
    for m in _PATTERN_CELL.finditer(text):
        num_str = m.group(1)
        unit = m.group(2)
        nearby = text[max(0, m.start() - 30):m.start() + 30]
        if _has_exclude_word(nearby):
            continue
        mw = _unit_to_mw(num_str, unit)
        if mw is None:
            continue
        period_label, duration_months, years = _detect_period(text, m.start(1), m.end(1))
        excerpt = _excerpt(text, m.start(), m.end())
        candidates.append((m.start(), BudgetInfo(
            mw=mw,
            period_label=period_label,
            raw_excerpt=excerpt,
            confidence="medium",
            duration_months=duration_months,
            years_covered=years,
        )))

    if candidates:
        candidates.sort(key=lambda x: x[0])
        return candidates[0][1]

    return None


# ─────────────────────────────────────────────────────────────────────────────
# 하위 호환 — 기존 호출자 (pipeline 등)
# ─────────────────────────────────────────────────────────────────────────────
def extract_budget_mw(text: str | None) -> int | None:
    """하위 호환: 백만원 단위 int만 반환."""
    info = extract_budget_info(text)
    return info.mw if info else None


def extract_duration_months(text: str | None) -> int | None:
    """본문에서 사업기간(개월) 추출."""
    if not text:
        return None
    m = _PERIOD_DURATION.search(text)
    if m:
        n = int(m.group(1))
        return n * 12 if m.group(2) == "년" else n
    return None
