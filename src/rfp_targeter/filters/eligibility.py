"""창업 N년차 자격 자동 검증.

정부 R&D 사업 일부는 '창업 N년 이내', '예비창업', '초기창업' 같은
자격 조건이 있어. 회사 established_year(profile.yaml)와 비교해서
부적합 시 [자격 미달] 배지 표시.

방침: **점수는 깎지 않음**. 거짓 양성(false positive) 위험 회피.
사용자가 배지 보고 직접 검토 후 판단.

거짓 양성 예시:
  - "창업 5년차 우수 사례 발표" — 자격이 아니라 단순 언급
  - "예비창업자 멘토링 제공" — 자격이 아니라 우대사항
  → 따라서 '신청 자격', '지원 대상', '참여 자격' 같은 인접 컨텍스트
     키워드를 함께 확인해야 신뢰도 ↑
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime


# 자격 조건 컨텍스트 키워드 — 이 키워드 근처에서 '창업 N년' 패턴 잡을 때 신뢰도 ↑
ELIGIBILITY_CONTEXT = [
    "신청자격", "신청 자격", "지원자격", "지원 자격",
    "참여자격", "참여 자격", "지원대상", "지원 대상",
    "신청대상", "신청 대상", "참여대상", "참여 대상",
    "대상기업", "대상 기업", "신청기업", "신청 기업",
    "모집대상", "모집 대상", "자격요건", "자격 요건",
]

# 창업 N년 패턴
_PATTERNS = [
    # 1) '창업 7년 이내', '창업 5년 미만', '창업 후 3년 이내'
    (re.compile(r"창업\s*(?:후\s*)?(\d{1,2})\s*년\s*(?:이내|미만|이하)"), "creation_within"),
    # 2) 'N년 이내 창업기업', 'N년 미만 창업'
    (re.compile(r"(\d{1,2})\s*년\s*(?:이내|미만)\s*창업"), "creation_within"),
    # 3) '예비창업'
    (re.compile(r"예비\s*창업"), "pre_creation"),
    # 4) '초기창업' (보통 3년 이내)
    (re.compile(r"초기\s*창업"), "early_creation"),
    # 5) '재도전 창업' (보통 7년 이내, 폐업 후 재창업)
    (re.compile(r"재도전\s*창업"), "redo_creation"),
    # 6) '청년창업' (만 39세 이하 - 회사 단위로 안 맞지만 일부 사업 기준)
    (re.compile(r"청년\s*창업"), "youth_creation"),
]

# 패턴 → 묵시적 연한 (사업 표준 관행 기준)
_IMPLICIT_YEARS = {
    "pre_creation":   0,   # 아예 미설립
    "early_creation": 3,
    "redo_creation":  7,
    "youth_creation": -1,  # 회사 연차로 판단 불가 (대표자 나이 기준)
}


@dataclass
class EligibilityResult:
    """자격 검증 결과.

    status:
      - 'ok'         : 명시적 자격 조건 없거나 회사 충족
      - 'blocked'    : 자격 미달 (신청 불가능 의심)
      - 'unsure'     : 자격 언급은 있으나 회사 연차로 판단 불가 (예: 청년창업, 대표자 나이)
      - 'unknown'    : 회사 established_year 미설정 → 검증 skip
    note:  표시용 한 줄 설명 (None이면 표시 안 함)
    limit_years:  추출된 N년 (없으면 None)
    """
    status: str
    note: str | None = None
    limit_years: int | None = None


def _has_context(text: str, match_pos: int, window: int = 60) -> bool:
    """매칭 위치 주변 +-window 글자 안에 자격 컨텍스트 키워드가 있는지."""
    start = max(0, match_pos - window)
    end = min(len(text), match_pos + window)
    snippet = text[start:end].replace(" ", "")
    for ctx in ELIGIBILITY_CONTEXT:
        if ctx.replace(" ", "") in snippet:
            return True
    return False


def check_eligibility(
    body: str | None,
    title: str | None = None,
    established_year: int | None = None,
    now: datetime | None = None,
) -> EligibilityResult:
    """공고 본문에서 창업 N년 자격을 추출하고 회사 연차와 비교.

    Args:
        body:  공고 본문 (없으면 제목만)
        title:  공고 제목 (본문 부재 시 폴백)
        established_year:  회사 설립 연도 (profile.yaml established_year)
        now:  기준 시점 (테스트용, 기본 datetime.now())

    Returns:
        EligibilityResult — 카드 배지 표시에 사용
    """
    if established_year is None or not isinstance(established_year, int):
        return EligibilityResult(status="unknown")
    if now is None:
        now = datetime.now()
    company_age = now.year - established_year

    haystack = ((body or "") + " " + (title or "")).strip()
    if not haystack:
        return EligibilityResult(status="ok")

    most_strict_limit: int | None = None
    most_strict_kind: str | None = None
    unsure = False

    for pat, kind in _PATTERNS:
        for m in pat.finditer(haystack):
            # 컨텍스트 키워드 확인 — 단순 언급 제외
            if not _has_context(haystack, m.start()):
                continue

            if kind in ("creation_within",):
                years = int(m.group(1))
            else:
                years = _IMPLICIT_YEARS.get(kind, -1)

            if years < 0:
                # 회사 연차로 판단 불가 (예: 청년창업 — 대표자 나이 기준)
                unsure = True
                continue

            # 가장 엄격한(가장 짧은) 연한 채택
            if most_strict_limit is None or years < most_strict_limit:
                most_strict_limit = years
                most_strict_kind = kind

    if most_strict_limit is None:
        if unsure:
            return EligibilityResult(
                status="unsure",
                note="청년창업 등 대표자 기준 자격 — 별도 확인",
            )
        return EligibilityResult(status="ok")

    # 비교
    if company_age <= most_strict_limit:
        # 회사 연차가 한도 이내 = 적합
        return EligibilityResult(
            status="ok",
            note=f"창업 {most_strict_limit}년 이내 자격 충족 (회사 {company_age}년차)",
            limit_years=most_strict_limit,
        )

    # 회사 연차 초과 = 부적합
    if most_strict_kind == "pre_creation":
        desc = "예비창업자 대상 (회사 설립 후 불가)"
    elif most_strict_kind == "early_creation":
        desc = "초기창업(보통 3년 이내) 대상"
    elif most_strict_kind == "redo_creation":
        desc = "재도전 창업(7년 이내) 대상"
    else:
        desc = f"창업 {most_strict_limit}년 이내 대상"

    return EligibilityResult(
        status="blocked",
        note=f"{desc} · 회사 {company_age}년차로 자격 미달 가능",
        limit_years=most_strict_limit,
    )
