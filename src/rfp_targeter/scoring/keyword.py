"""키워드·테마 적합도 산정."""
from __future__ import annotations

from rfp_targeter.db.models import Announcement


def _norm(s: str) -> str:
    return (s or "").replace(" ", "").lower()


def _blob(a: Announcement) -> str:
    return _norm(" ".join(filter(None, [a.title, a.summary, a.body, " ".join(a.matched_keywords)])))


def score_keyword(a: Announcement, profile: dict) -> tuple[float, list[str]]:
    """공고 본문에 회사 핵심 키워드가 얼마나 등장하는지.

    매칭 개수 기반(키워드 사전 크기에 무관). boost 매칭도 가산.
    """
    core = profile.get("core_keywords") or []
    positioning = profile.get("positioning_keywords") or []
    blob = _blob(a)

    if not core or core == ["???"]:
        return 50.0, ["profile.yaml 의 core_keywords 미설정 — 중립 점수 50점"]

    core_hits = [k for k in core if _norm(k) in blob]
    pos_hits = [k for k in positioning if _norm(k) in blob]

    # 핵심 키워드 매칭당 12점 (9개 매칭이면 만점), positioning 키워드는 8점
    score = min(100.0, len(core_hits) * 12 + len(pos_hits) * 8)

    # 보안 필터의 boost 매칭도 가산 (이미 a.matched_keywords 에 포함됨)
    boost_n = max(0, len(a.matched_keywords) - len(core_hits))
    if boost_n:
        score = min(100.0, score + boost_n * 2)

    why: list[str] = []
    if core_hits:
        shown = ", ".join(core_hits[:6])
        more = f" 외 {len(core_hits) - 6}개" if len(core_hits) > 6 else ""
        why.append(f"핵심 키워드 {len(core_hits)}개 매칭: {shown}{more}")
    if pos_hits:
        why.append(f"포지셔닝 키워드 매칭: {', '.join(pos_hits[:4])}")
    if a.matched_keywords:
        why.append(f"보안 필터 매칭 {len(a.matched_keywords)}개: {', '.join(a.matched_keywords[:6])}")
    if not why:
        why.append("회사 키워드 매칭 없음")
    return score, why


def score_theme_fit(a: Announcement, profile: dict) -> tuple[float, list[str]]:
    """회사 테마(보유 기술 + 핵심 키워드) 종합 적합도."""
    blob = _blob(a)
    techs = profile.get("technologies") or []

    score = 30.0  # baseline
    why: list[str] = []

    tech_hits = []
    for t in techs:
        for kw in t.get("keywords", []):
            if kw and _norm(kw) in blob:
                tech_hits.append(t["name"])
                break
    if tech_hits:
        score += min(40.0, len(tech_hits) * 15)
        why.append(f"보유 기술 매칭: {', '.join(tech_hits)}")

    core_hits = [k for k in (profile.get("core_keywords") or []) if _norm(k) in blob]
    if core_hits:
        score += min(30.0, len(core_hits) * 5)
        why.append(f"핵심 키워드 매칭 {len(core_hits)}개")

    return min(100.0, score), why or ["테마 매칭 없음 — baseline 점수"]
