"""컨소시엄 구성 부담 — 본문 분석으로 추정.

회사가 단독 수행 가능 vs 다기관 컨소시엄 필수 vs 대학·연구소 참여 필수 등을
키워드로 판단. 정밀하진 않지만 점수 차이 만드는 데 충분.

[2026-05-27 ecosystem 가점 추가]
컨소시엄·다기관 신호 있는 공고에 한해 회사 ecosystem_partners (8개사)
영역(domain) 매칭 시 가점. "협력 시너지 기회" 의미장.
"""
from __future__ import annotations

from rfp_targeter.db.models import Announcement


CONSORTIUM_SIGNALS = {
    "대학_필수": ["대학", "산학", "교수", "박사후", "산학협력"],
    "다기관": ["컨소시엄", "공동연구", "주관·공동", "참여기관"],
    "정부출연연": ["출연연", "ETRI", "KAIST", "KISTI", "한국전자통신연구원"],
}


def score_consortium(a: Announcement, profile: dict) -> tuple[float, list[str]]:
    cons = profile.get("consortium") or {}
    blob = (a.body or a.summary or "").lower()
    title = (a.title or "")
    full = (blob + " " + title).lower()

    signals = {
        name: [w for w in words if w.lower() in full]
        for name, words in CONSORTIUM_SIGNALS.items()
    }
    has_uni = bool(signals["대학_필수"])
    has_multi = bool(signals["다기관"])

    score = 100.0
    why: list[str] = []
    parts: list[str] = []
    university_ready = cons.get("university_partner_available", False)
    max_partners = cons.get("max_partners", 3)

    if has_uni and not university_ready:
        score -= 35
        why.append("대학 참여 필요 신호 — 회사 대학 파트너 미설정")
        parts.append("대학필요·파트너X −35")
    elif has_uni and university_ready:
        score -= 5
        why.append("대학 참여 필요 신호 — KAIST 등 회사 보유 대학 파트너 활용 가능")
        parts.append("대학필요·KAIST활용 −5")

    if has_multi:
        if max_partners >= 3:
            score -= 10
            why.append("다기관 컨소시엄 필요 — 회사 가능 범위 내")
            parts.append("다기관·가능 −10")
        else:
            score -= 30
            why.append(f"다기관 컨소시엄 필요 — 회사 max {max_partners} 초과 우려")
            parts.append(f"다기관·max초과 −30")

    if not has_uni and not has_multi:
        # 컨소시엄 신호 약함 — 단독 수행 가능. 다만 100점 만점은 강한 신호일 때만
        if cons.get("solo_capable"):
            why.append("컨소시엄 신호 약함 + 회사 단독 수행 능력 입증 — 만점")
            parts.append("단독수행 가능 0")
        else:
            score -= 10
            why.append("컨소시엄 신호 약함 — 단독 수행 가능성 (회사 단독수행 능력 미명시)")
            parts.append("단독수행 미명시 −10")

    # ── ecosystem_partners 가점 (컨소시엄 신호 있을 때만 의미) ──────────
    # 공고가 컨소시엄/다기관 요구 + 본문에 ecosystem 파트너 도메인 매칭
    # → 협력 시너지 가능 → 가점.
    # has_uni 또는 has_multi 가 true 일 때만 발동 (단독 수행 공고엔 무의미)
    if has_uni or has_multi:
        ecosystem = profile.get("ecosystem_partners") or []
        eco_matches: list[str] = []
        for p in ecosystem:
            name = p.get("name", "")
            domain = p.get("domain", "")
            if not domain:
                continue
            # domain 안에 콤마로 구분된 영역들 (예: "RBI, WAF")
            areas = [a.strip().lower() for a in domain.split(",") if a.strip()]
            if any(area and area in full for area in areas):
                eco_matches.append(name)
        if eco_matches:
            # 매칭 1개당 +3, cap +10
            bonus = min(10, len(eco_matches) * 3)
            score += bonus
            why.append(
                f"ecosystem 파트너 영역 매칭 ({len(eco_matches)}곳, 협력 시너지 가능): "
                f"{', '.join(eco_matches[:3])}"
            )
            parts.append(f"eco({len(eco_matches)}×3) +{bonus}")

    score = max(0.0, min(100.0, score))
    why.append(f"📐 산정: 100 {' '.join(parts) if parts else '(변동없음)'} → **{score:.0f}점**")
    return score, why
