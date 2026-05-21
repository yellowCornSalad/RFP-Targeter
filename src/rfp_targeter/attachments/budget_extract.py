"""공고 본문에서 예산(사업비) 추출 — 모든 크롤러 공통.

설계:
- 한국 정부 R&D 공고 본문의 다양한 표현을 모두 흡수
  · "사업비 2,800백만원"
  · "총사업비 1.5억원"
  · "정부출연금 4,429.76억원"
  · "연구비 76.33억"
  · "과제당 4.6억원"
  · "지원 규모 200억원"
  · "1,200,000,000원"
- 소수점·콤마·공백 변형 모두 처리
- 백만원 단위로 정규화 (DB schema)
- 비현실적 값 필터링 (1억 미만 / 10조 초과)

사용:
    from rfp_targeter.attachments.budget_extract import extract_budget_mw
    budget_mw = extract_budget_mw(body_text)  # int | None
"""
from __future__ import annotations

import re

# prefix 키워드 — 본문에서 이 단어 근처의 숫자만 예산으로 인정
# (단순 숫자 매칭으로 페이지 번호·날짜·과제번호 등 잡지 않게)
_PREFIX_PATTERN = (
    r"(?:총\s*)?(?:사업\s*비|연구\s*비|예\s*산|정부\s*출연금|"
    r"지원\s*금액|지원\s*규모|사업\s*규모|투자\s*규모|"
    r"과제\s*당|총\s*연구\s*비|총\s*예산|총\s*투자)"
)

# 숫자 패턴 — 콤마·소수점 허용
# 예: 2,800 / 1.5 / 4,429.76 / 100
_NUM_PATTERN = r"(\d[\d,]*(?:\.\d+)?)"

# 단위 패턴 — 가장 큰 단위부터 (정규식 greedy 작동)
_UNIT_PATTERN = (
    r"(억\s*원?|백\s*만\s*원|만\s*원|천\s*원|원)"
)

# prefix + (10자 이내 임의) + 숫자 + (5자 이내) + 단위
_FULL_RE = re.compile(
    _PREFIX_PATTERN + r"[^\d]{0,30}" + _NUM_PATTERN + r"\s*" + _UNIT_PATTERN,
    re.IGNORECASE,
)


def _num_to_mw(num_str: str, unit: str) -> int | None:
    """숫자 + 단위 → 백만원."""
    try:
        n = float(num_str.replace(",", ""))
    except ValueError:
        return None
    if n <= 0:
        return None

    u = re.sub(r"\s+", "", unit)
    if u in ("억", "억원"):
        mw = int(round(n * 100))  # 1억 = 100백만
    elif u in ("백만원",):
        mw = int(round(n))
    elif u in ("만원",):
        mw = int(round(n / 100))  # 100만원 = 1백만
    elif u in ("천원",):
        mw = int(round(n / 100000))  # 1억원 = 100,000천원 = 100백만
    elif u in ("원",):
        mw = int(round(n / 1_000_000))
    else:
        return None

    # 비현실적 값 필터:
    # - 1백만원 미만: 단가/참가비 등
    # - 1조원(=1,000,000백만원) 초과: 여러 해 누적치 또는 거짓 양성
    #   (단일 R&D 공고는 실무상 1조 이하 — 그 이상은 부처 통합 예산 누계)
    if mw < 1 or mw > 1_000_000:
        return None
    return mw


def extract_budget_mw(text: str | None) -> int | None:
    """본문에서 예산을 추출. 발견된 첫 번째 합리적 값을 백만원 단위로 반환.

    Returns:
        백만원 단위 int (예: 2800 = 28억) 또는 None (못 찾음)
    """
    if not text:
        return None

    # 모든 매칭 후보 수집
    candidates: list[int] = []
    for m in _FULL_RE.finditer(text):
        num_str, unit = m.group(1), m.group(2)
        mw = _num_to_mw(num_str, unit)
        if mw is not None:
            candidates.append(mw)

    if not candidates:
        return None

    # 보통 본문 첫 부분의 "총사업비"가 가장 권위 있음
    # 단 너무 작은 값(< 50백만)은 단가 언급일 수 있으니 후순위
    primary = [c for c in candidates if c >= 50]
    return primary[0] if primary else candidates[0]


def extract_duration_months(text: str | None) -> int | None:
    """본문에서 사업기간(개월) 추출 — 보조 유틸."""
    if not text:
        return None
    m = re.search(
        r"(?:사업\s*기간|연구\s*기간|총\s*연구기간|수행\s*기간)"
        r"[^\d]{0,20}(\d+)\s*(개월|년)",
        text,
    )
    if m:
        n = int(m.group(1))
        return n * 12 if m.group(2) == "년" else n
    return None
