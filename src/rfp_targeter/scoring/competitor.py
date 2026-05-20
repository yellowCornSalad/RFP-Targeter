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
    score = 60.0  # baseline

    high_hits = [k for k in GENERIC_HIGH_COMPETITION if k.lower() in blob]
    low_hits = [k for k in GENERIC_LOW_COMPETITION if k.lower() in blob]

    if high_hits:
        score -= min(30, len(high_hits) * 15)
        why.append(f"대형 경쟁 영역 신호: {', '.join(high_hits)}")
    if low_hits:
        score += min(30, len(low_hits) * 15)
        why.append(f"전문 영역 신호 (경쟁 적음 추정): {', '.join(low_hits)}")

    # 경쟁사 이름이 본문에 명시되어 있으면(드물지만) 강한 신호
    rivals = [r for r in (profile.get("competitors") or []) if r.lower() in blob]
    if rivals:
        score -= 15
        why.append(f"본문에 경쟁사 언급: {', '.join(rivals)}")

    return max(0.0, min(100.0, score)), why or ["경쟁 신호 약함 — baseline"]
