"""키워드·테마 적합도 산정."""
from __future__ import annotations

from rfp_targeter.db.models import Announcement


def _norm(s: str) -> str:
    return (s or "").replace(" ", "").lower()


def _blob(a: Announcement) -> str:
    return _norm(" ".join(filter(None, [a.title, a.summary, a.body, " ".join(a.matched_keywords)])))


def score_keyword(a: Announcement, profile: dict) -> tuple[float, list[str]]:
    """공고 본문에 회사 핵심 키워드가 얼마나 등장하는지.

    설계:
    - 회사 core_keywords (OFFen·ASM 등 자체 제품명)는 정부 공고에 거의 안 나옴.
      따라서 baseline 0이면 너무 박함. 보안 필터 통과 = 회사 영역 ⇒ baseline 30 부여.
    - 매칭 1건당 가중치 강화: core 18 / positioning 12 / boost 8
    - 정량: 양자내성암호 사업(core 2 + boost 2) → 30 + 36 + 16 = 82
    - 정량: 일반 보안 공고(core 0 + boost 3) → 30 + 24 = 54
    """
    core = profile.get("core_keywords") or []
    positioning = profile.get("positioning_keywords") or []
    blob = _blob(a)

    if not core or core == ["???"]:
        return 50.0, ["profile.yaml 의 core_keywords 미설정 — 중립 점수 50점"]

    core_hits = [k for k in core if _norm(k) in blob]
    pos_hits = [k for k in positioning if _norm(k) in blob]
    boost_n = max(0, len(a.matched_keywords) - len(core_hits))

    # 보안 필터 통과 또는 회사 키워드 1+ 매칭이면 baseline 30
    has_any_match = bool(core_hits or pos_hits or a.matched_keywords)
    baseline = 30.0 if has_any_match else 0.0

    # 매칭 가중치 (이전 12/8/4 → 18/12/8)
    score = min(
        100.0,
        baseline
        + len(core_hits) * 18
        + len(pos_hits) * 12
        + boost_n * 8,
    )

    # 매칭 풍부도 보너스: 보안 필터 8개 이상이면 +5 (회사 영역 직접 신호)
    if len(a.matched_keywords) >= 8:
        score = min(100.0, score + 5)

    why: list[str] = []
    parts = []
    if has_any_match:
        parts.append(f"baseline {int(baseline)}")
    if core_hits:
        shown = ", ".join(core_hits[:6])
        more = f" 외 {len(core_hits) - 6}개" if len(core_hits) > 6 else ""
        why.append(f"핵심 키워드 {len(core_hits)}개 매칭: {shown}{more}")
        parts.append(f"core {len(core_hits)}×18")
    if pos_hits:
        why.append(f"포지셔닝 키워드 매칭: {', '.join(pos_hits[:4])}")
        parts.append(f"pos {len(pos_hits)}×12")
    if a.matched_keywords:
        why.append(f"보안 필터 매칭 {len(a.matched_keywords)}개: {', '.join(a.matched_keywords[:6])}")
        if boost_n:
            parts.append(f"boost {boost_n}×8")
        if len(a.matched_keywords) >= 8:
            parts.append("매칭 풍부 +5")
    if not why:
        why.append("회사 키워드 매칭 없음")
    if parts:
        why.append(f"📐 산정: {' + '.join(parts)} = **{score:.0f}점**")
    return score, why


def score_theme_fit(a: Announcement, profile: dict) -> tuple[float, list[str]]:
    """회사 테마(보유 기술 + 핵심 키워드 + 포지셔닝 + 보안 필터 매칭) 종합 적합도."""
    blob = _blob(a)
    techs = profile.get("technologies") or []

    score = 25.0
    why: list[str] = []

    # 보유 기술 매칭 (가장 강한 신호)
    tech_hits = []
    for t in techs:
        for kw in t.get("keywords", []):
            if kw and _norm(kw) in blob:
                tech_hits.append(t["name"])
                break
    if tech_hits:
        score += min(40.0, len(tech_hits) * 15)
        why.append(f"보유 기술 매칭 {len(tech_hits)}개: {', '.join(t.split('(')[0].strip() for t in tech_hits[:3])}")

    # 핵심 키워드 매칭
    core_hits = [k for k in (profile.get("core_keywords") or []) if _norm(k) in blob]
    if core_hits:
        score += min(20.0, len(core_hits) * 4)
        why.append(f"핵심 키워드 매칭 {len(core_hits)}개")

    # 포지셔닝 키워드 매칭 (직접 메시지 일치)
    pos_hits = [k for k in (profile.get("positioning_keywords") or []) if _norm(k) in blob]
    if pos_hits:
        score += min(15.0, len(pos_hits) * 6)
        why.append(f"포지셔닝 직접 매칭: {', '.join(pos_hits[:3])}")

    # 보안 필터 매칭 키워드 — 회사 특기 영역 직접 신호
    matched_n = len(a.matched_keywords or [])
    if matched_n >= 6:
        score += 25
        why.append(f"보안 필터 매칭 풍부 ({matched_n}개)")
    elif matched_n >= 3:
        score += 15
        why.append(f"보안 필터 매칭 다수 ({matched_n}개)")
    elif matched_n >= 1:
        score += 8

    # 본문 풍부도
    if len(a.body or "") > 1500:
        score += 3
        why.append("본문 정보 풍부 (+3)")

    # 발주 부서 티어 가산 (IITP/MSIT 공고에서 본문 부족 보정)
    tiers = profile.get("agency_tiers") or {}
    if a.agency:
        ag = a.agency.strip()
        if ag in (tiers.get("tier1_security") or []):
            score += 25
            why.append(f"보안 직격 부서 발주 [+25]: {ag}")
        elif ag in (tiers.get("tier2_core") or []):
            score += 15
            why.append(f"회사 본업 핵심 부서 [+15]: {ag}")
        elif ag in (tiers.get("tier3_adjacent") or []):
            score += 8
            why.append(f"인접 영역 부서 [+8]: {ag}")

    score = min(100.0, score)
    why.append(f"📐 산정: baseline 25 + 가산 → **{score:.0f}점**")
    return score, why or ["테마 매칭 없음 — 낮은 baseline"]
