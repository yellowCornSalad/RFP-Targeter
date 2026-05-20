"""컨소시엄 구성 부담 — 본문 분석으로 추정.

회사가 단독 수행 가능 vs 다기관 컨소시엄 필수 vs 대학·연구소 참여 필수 등을
키워드로 판단. 정밀하진 않지만 점수 차이 만드는 데 충분.
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
    full = blob + " " + title

    signals = {
        name: [w for w in words if w.lower() in full]
        for name, words in CONSORTIUM_SIGNALS.items()
    }
    has_uni = bool(signals["대학_필수"])
    has_multi = bool(signals["다기관"])

    score = 100.0
    why: list[str] = []
    university_ready = cons.get("university_partner_available", False)
    max_partners = cons.get("max_partners", 3)

    if has_uni and not university_ready:
        score -= 35
        why.append("대학 참여 필요 신호 — 회사 대학 파트너 미설정")
    elif has_uni and university_ready:
        why.append("대학 참여 필요 신호 — 회사 보유 대학 파트너 활용 가능")

    if has_multi:
        if max_partners >= 3:
            score -= 10
            why.append("다기관 컨소시엄 필요 — 회사 가능 범위 내")
        else:
            score -= 30
            why.append(f"다기관 컨소시엄 필요 — 회사 max {max_partners} 초과 우려")

    if not has_uni and not has_multi:
        why.append("컨소시엄 신호 약함 — 단독 수행 가능성")

    return max(0.0, score), why
