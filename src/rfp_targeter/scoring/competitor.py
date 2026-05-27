"""경쟁자 상황 추정 — 본문 키워드 + 발주기관 기반 휴리스틱.

[2026-05-27 v2 재설계] 73%가 baseline 50점 묶임 문제 해결

이전 문제:
- 키워드 풀 너무 좁음 (저경쟁 7개, 고경쟁 4개)
- "PQC/AI 보안/공격 시뮬레이션" 외 회사 본업 키워드 누락
- 발주기관 가중치 없음 → KISA 회사 강점 사업도 baseline

새 설계:
- 회사 본업 키워드 대폭 확장 (모의해킹/침투/CTEM/Red Team 등 18개)
- 대기업 영역 키워드 확장 (SOC/SIEM/SI/통신 등 10개)
- 발주기관 가중치 (KISA 보안 사업 회사 강점 +10, 대기업 SI 영역 -5)
- 본문 풍부도 신뢰도 가중

⚠️ 한계: 실제 응찰자 수는 모름. 본문 키워드 기반 추정치임.
"""
from __future__ import annotations

from rfp_targeter.db.models import Announcement


# ── 회사 본업 영역 (저경쟁 추정 → 가점) ──────────────────────────────────
# 회사 ENKI WhiteHat 본업: 오펜시브 보안 / 공격 검증 / 침투 자동화
LOW_COMPETITION_KEYWORDS = [
    # 오펜시브 직격
    "모의해킹", "침투테스트", "침투 테스트", "취약점 진단", "취약점진단",
    "공격 시뮬레이션", "공격시뮬레이션", "Red Team", "레드팀",
    "화이트해커", "화이트 해커", "보안 자동화", "보안자동화",
    "ASM", "공격표면", "Attack Surface", "CTEM",
    "AI 보안", "AI보안", "AI DAST", "AI Hacker",
    # 전문 암호/인증 영역
    "양자내성", "PQC", "포스트퀀텀", "동형암호", "비밀계산",
    # 임베디드/펌웨어
    "펌웨어 보안", "임베디드 보안",
    # 보안 검증 일반
    "보안성 검증", "보안성검증", "취약점 분석", "취약점분석",
    "사이버 위협 인텔리전스", "위협 인텔리전스",
]

# ── 대기업/대형 SI 영역 (고경쟁 추정 → 감점) ──────────────────────────
# 회사 약세 영역: 대규모 운영 / 통합관제 / SI / 통신 인프라
HIGH_COMPETITION_KEYWORDS = [
    "통합관제", "통합 관제", "통합보안관제", "통합 보안 관제",
    "관제 서비스", "MSSP", "SOAR",
    "SOC", "SIEM",  # 운영 영역 (대기업 강세)
    "통합 플랫폼", "통합플랫폼", "차세대 보안 플랫폼",
    "IT 인프라", "ICT 기반시설", "통신 보안",
    "사내망 보안", "사내 망 보안",
    "전산실 구축", "데이터센터 보안",
]

# ── 발주기관 가중치 (회사 강점 부처 매칭) ───────────────────────────────
# KISA 보안 신기술 사업 — 회사 KISA 2026 신기술 선정 (50개 기업 중 1)
AGENCY_BOOST = {
    "KISA": 10,           # 회사 강점 부처
    "한국인터넷진흥원": 10,
    "정보통신산업진흥원": 5,   # NIPA — 일반 R&D
    "IITP": 5,            # 정보통신기획평가원 R&D
}
AGENCY_PENALTY = {
    "조달청": -3,            # 일반 입찰 — 경쟁 보통
}


def score_competitor(a: Announcement, profile: dict) -> tuple[float, list[str]]:
    blob = ((a.title or "") + " " + (a.summary or "") + " " + (a.body or "")).lower()
    agency = (a.agency or "").strip()

    why: list[str] = []
    parts: list[str] = []
    score = 50.0  # baseline (정보 없으면 중간)

    # ── 1. 회사 본업 키워드 (저경쟁 가점) ─────────────────────────────
    low_hits = [k for k in LOW_COMPETITION_KEYWORDS if k.lower() in blob]
    if low_hits:
        # 매칭당 +8, cap +35
        delta = min(35, len(low_hits) * 8)
        score += delta
        why.append(f"회사 본업 영역 신호 ({len(low_hits)}개): {', '.join(low_hits[:5])}")
        parts.append(f"본업({len(low_hits)}×8) +{delta}")

    # ── 2. 대기업 영역 키워드 (고경쟁 감점) ────────────────────────────
    high_hits = [k for k in HIGH_COMPETITION_KEYWORDS if k.lower() in blob]
    if high_hits:
        # 매칭당 -10, cap -30
        delta = min(30, len(high_hits) * 10)
        score -= delta
        why.append(f"대기업 강한 영역 신호 ({len(high_hits)}개): {', '.join(high_hits[:5])}")
        parts.append(f"대기업영역({len(high_hits)}×10) -{delta}")

    # ── 3. 발주기관 가중치 ────────────────────────────────────────────
    for kw, boost in AGENCY_BOOST.items():
        if kw in agency:
            score += boost
            why.append(f"발주기관 가산 [{agency}]: +{boost} (회사 강점)")
            parts.append(f"기관+{boost}")
            break
    for kw, pen in AGENCY_PENALTY.items():
        if kw in agency:
            score += pen  # pen 은 음수
            parts.append(f"기관{pen}")
            break

    # ── 4. 본문 풍부도 신뢰도 ────────────────────────────────────────
    body_len = len(a.body or "")
    if body_len < 200:
        score -= 5
        parts.append("본문부족 -5")

    # ── 5. 회사 경쟁사 본문 등장 (강한 신호) ─────────────────────────
    rivals = [r for r in (profile.get("competitors") or []) if r.lower() in blob]
    if rivals:
        score -= 15
        why.append(f"본문에 경쟁사 언급: {', '.join(rivals)}")
        parts.append("경쟁사명시 -15")

    score = max(0.0, min(100.0, score))
    if not why:
        why = ["경쟁 신호 약함 — baseline 50 유지"]
    why.append(f"📐 산정: baseline 50 {' '.join(parts) if parts else '(변동없음)'} → **{score:.0f}점**")
    return score, why
