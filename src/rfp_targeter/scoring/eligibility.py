"""자격 적합도 (eligibility_fit) — 본문 자격 요건 vs 회사 자격 매칭.

[2026-05-27 신규] consortium 점수 대체.

이유:
- consortium 분포가 80~100 사이에 압축됨 (회사 자산 풍부 — 5 파트너 + KAIST 공동특허
  + solo_capable). 거의 모든 공고가 85+ 라 변별력 거의 없음.
- 대신 자격 요건 매칭으로 변별력 확보. 응찰 가능 여부를 직접 점수화.

회사 자격 (profile.yaml 기반):
- 중소기업 (company.size = "중소")
- 창업 10년차 (established_year=2016, 현재 2026)
- 정보보호 전문기업 (KISA 2026 신기술 선정 — 50개 기업 중 1)
- 보안 전문 인력 보유 (화이트해커 23.8만 건 DB)

자격 매칭 패턴:

POSITIVE (회사 매칭 → 가점):
- "중소기업 한정/우대"             → +20 (회사 매칭)
- "정보보호 전문기업"              → +20 (회사 KISA 선정)
- "보안 전문 인력 N명 이상"        → +15
- "창업 N년 이내"                  → +20 (회사 10년차 매칭 시)

NEGATIVE (회사 부적합 → 감점):
- "박사후/대학원생" 한정            → -50 (응찰 불가)
- "대기업 한정"                     → -40
- "비영리법인/공공기관" 단독 한정   → -40
- "창업 N년 이내" 인데 회사 초과    → -30

NEUTRAL (자격 명시 없음):
- baseline 60 (자격 요건 명시 없으면 자유 응찰 가능 → 긍정적 default)

DB 컬럼: consortium_score (legacy, 마이그레이션 회피용 — 의미만 eligibility 로 교체)
"""
from __future__ import annotations

import re
from datetime import datetime

from rfp_targeter.db.models import Announcement


def _company_age(profile: dict) -> int:
    """회사 연차 = 현재 연도 - 창업 연도."""
    company = profile.get("company") or {}
    established = company.get("established_year")
    if not isinstance(established, int):
        return 0
    return datetime.now().year - established


def score_eligibility(a: Announcement, profile: dict) -> tuple[float, list[str]]:
    """자격 적합도 — 본문 자격 요건 vs 회사 매칭 (이전 consortium 대체)."""
    blob = ((a.title or "") + " " + (a.summary or "") + " " + (a.body or "")).lower()
    company = profile.get("company") or {}
    size = (company.get("size") or "").strip()
    age = _company_age(profile)

    score = 60.0  # baseline (자격 명시 없으면 자유 응찰 가정)
    why: list[str] = []
    parts: list[str] = []
    matched = False

    # ── 1. 중소기업 한정/우대 ───────────────────────────────────────
    if any(kw in blob for kw in ["중소기업 한정", "중소기업 우대", "중소기업만"]):
        matched = True
        if size in ("중소", "중소기업", "벤처", "중견"):
            score += 20
            why.append(f"중소기업 우대/한정 — 회사({size}) 매칭")
            parts.append("중소기업 +20")
        else:
            score -= 20
            why.append(f"중소기업 한정인데 회사({size}) 비매칭")
            parts.append("중소비매칭 −20")

    # ── 2. 정보보호 전문기업 우대 ───────────────────────────────────
    if any(kw in blob for kw in ["정보보호 전문기업", "정보보호전문기업", "정보보호전문서비스기업", "보안 전문기업", "보안전문기업"]):
        matched = True
        score += 20
        why.append("정보보호 전문기업 우대 — 회사 KISA 2026 신기술 선정")
        parts.append("정보보호전문 +20")

    # ── 3. 보안 전문 인력 요구 ──────────────────────────────────────
    if any(kw in blob for kw in ["보안 전문 인력", "보안전문인력", "정보보호 전문 인력", "정보보호전문인력", "화이트해커"]):
        matched = True
        score += 15
        why.append("보안 전문 인력 요구 — 회사 화이트해커 보유")
        parts.append("보안인력 +15")

    # ── 4. 창업 N년 이내 ────────────────────────────────────────────
    m = re.search(r"창업\s*(\d+)\s*년\s*이내", blob)
    if m:
        matched = True
        n = int(m.group(1))
        if age <= n:
            score += 20
            why.append(f"창업 {n}년 이내 우대 — 회사 {age}년차 매칭")
            parts.append(f"창업{n}년이내 +20")
        else:
            score -= 30
            why.append(f"창업 {n}년 이내 한정 — 회사 {age}년차 초과")
            parts.append(f"창업초과 −30")

    # ── 5. 박사후/대학원생 한정 (회사 응찰 불가) ────────────────────
    if any(kw in blob for kw in ["박사후 연구원", "박사후연구원", "박사후 과정", "대학원생 한정", "대학원생만"]):
        matched = True
        score -= 50
        why.append("박사후/대학원생 한정 — 회사(기업) 응찰 불가")
        parts.append("학계한정 −50")

    # ── 6. 대기업 한정 ──────────────────────────────────────────────
    if any(kw in blob for kw in ["대기업 한정", "대기업만", "대기업·중견기업"]):
        matched = True
        score -= 40
        why.append(f"대기업 한정 — 회사({size}) 비매칭")
        parts.append("대기업한정 −40")

    # ── 7. 비영리법인/공공기관 단독 ─────────────────────────────────
    if any(kw in blob for kw in ["비영리법인 한정", "비영리 법인 한정", "비영리법인만", "공공기관 단독", "공공기관만"]):
        matched = True
        score -= 40
        why.append("비영리/공공 단독 한정 — 회사 비매칭")
        parts.append("비영리한정 −40")

    score = max(0.0, min(100.0, score))

    if not matched:
        why.append("자격 요건 본문 명시 없음 — 자유 응찰 가정 (baseline 60)")
    why.append(f"📐 산정: baseline 60 {' '.join(parts) if parts else '(변동없음)'} → **{score:.0f}점**")
    return score, why
