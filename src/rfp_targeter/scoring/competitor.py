"""경쟁자 상황 추정 — 본문에 잠재 경쟁사 키워드 등장 빈도.

회사의 typical 경쟁사 이름이 RFP 자체나 유사 공고 패턴에서 자주 등장하면
경쟁 강함 → 점수 낮음. 정밀하진 않지만 차별점 단서.

추후: 과거 수주 데이터 + 키워드 클러스터 + LLM 분석으로 강화.
"""
from __future__ import annotations

from rfp_targeter.db.models import Announcement


# 일반적인 경쟁 강도 휴리스틱
GENERIC_HIGH_COMPETITION = [
    "통합 플랫폼", "관제", "SOC", "SIEM",  # 대기업 강한 영역
]
GENERIC_LOW_COMPETITION = [
    "양자내성", "PQC", "동형암호", "비밀계산",  # 전문 영역
    "AI 보안", "공격 시뮬레이션", "보안성 검증",
]


def score_competitor(a: Announcement, profile: dict) -> tuple[float, list[str]]:
    blob = ((a.title or "") + " " + (a.summary or "") + " " + (a.body or "")).lower()
    why: list[str] = []
    parts: list[str] = []
    score = 50.0  # baseline 낮춤 (정보 없으면 중간)

    high_hits = [k for k in GENERIC_HIGH_COMPETITION if k.lower() in blob]
    low_hits = [k for k in GENERIC_LOW_COMPETITION if k.lower() in blob]

    if high_hits:
        d = min(35, len(high_hits) * 15)
        score -= d
        why.append(f"대형 경쟁 영역 신호: {', '.join(high_hits)}")
        parts.append(f"대형경쟁 −{d}")
    if low_hits:
        a_ = min(40, len(low_hits) * 15)
        score += a_  # 전문 영역 가산 강화
        why.append(f"전문 영역 신호 (경쟁 적음 추정): {', '.join(low_hits)}")
        parts.append(f"전문영역 +{a_}")

    # 본문이 풍부할수록 신뢰도 ↑
    body_len = len(a.body or "")
    if body_len < 200:
        score -= 5
        why.append("본문 정보 부족 — 신뢰도 낮춤")
        parts.append("본문부족 −5")

    # 경쟁사 이름이 본문에 명시되어 있으면(드물지만) 강한 신호
    rivals = [r for r in (profile.get("competitors") or []) if r.lower() in blob]
    if rivals:
        score -= 15
        why.append(f"본문에 경쟁사 언급: {', '.join(rivals)}")
        parts.append(f"경쟁사명시 −15")

    score = max(0.0, min(100.0, score))
    if not why:
        why = ["경쟁 신호 약함 — baseline"]
    why.append(f"📐 산정: baseline 50 {' '.join(parts) if parts else '(변동없음)'} → **{score:.0f}점**")
    return score, why
