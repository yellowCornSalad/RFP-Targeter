"""키워드·테마 적합도 산정.

[2026-05-27 재설계 v2] 100점 인플레이션 해결 + 현실 반영

진단 1차:
- 회사 core_keywords (48개) 매칭은 거의 0건 (ASM 1건만, 나머지 47개 모두 0건)
- 그런데도 100점 공고 31% (194/625) → boost_n × 8 가중치가 깡통
- 예: matched 31개 → 30 + 31×8 = 278 → cap 100 (회사 신호 0인데도)

진단 2차 (왜 core 매칭 0?):
- "모의해킹"·"침투"·"보안 자동화"·"공격 시나리오" 정부 공고 본문에 **0건** 등장
- "취약점"만 12건 — 정부 공고는 추상적 표현 위주, 회사 마케팅 용어 안 씀
- 즉 core_keywords 매칭 0은 버그 아니라 현실
- → 실제 변별력은 **일반 사전 매칭 (keywords.yaml) + 동의어 dedupe** 이 핵심

개선:
1. baseline 30 (보안 필터 통과 = 회사 영역 진입)
2. core 매칭 × 25 cap 50 (강한 신호, 가끔 매칭되면 큰 보너스)
3. positioning 매칭 × 10 cap 20 (포지셔닝 메시지 일치)
4. 일반 사전 매칭 = log2(n+1) × 7 cap 35 (10건 매칭 ≈ +24, 25건 ≈ +32, 포화 곡선)
5. 동의어 그룹화로 카운트 인플레이션 차단 ("보안/사이버보안/정보보호" → 1 카운트)
6. cap 100 유지 — core 또는 pos 가산되면 자연스럽게 100점 도달

목표 분포: 95-100 ~10%, 70-94 ~30%, 50-69 ~40%, ~50 ~20%
"""
from __future__ import annotations

import math

from rfp_targeter.db.models import Announcement


def _norm(s: str) -> str:
    return (s or "").replace(" ", "").lower()


def _blob(a: Announcement) -> str:
    return _norm(" ".join(filter(None, [a.title, a.summary, a.body, " ".join(a.matched_keywords)])))


# 동의어 그룹화 — keywords.yaml의 표기 변형을 1 카운트로 통합.
# 예: "보안/사이버보안/사이버 보안/정보보호/정보 보호" → 1 그룹.
# 카운트 인플레이션 차단 (한 의미를 5번 매칭으로 부풀리는 것 방지).
_SYNONYM_GROUPS: list[set[str]] = [
    {"보안", "사이버보안", "사이버 보안", "정보보호", "정보 보호"},
    {"인공지능", "AI", "에이아이"},
    {"소프트웨어", "SW", "에스더블유"},
    {"양자내성암호", "PQC", "포스트퀀텀암호"},
    {"AI 보안", "AI보안", "인공지능 보안"},
    {"OT 보안", "OT보안"},
    {"IoT 보안", "IoT보안"},
    {"머신러닝", "ML", "기계학습"},
    {"딥러닝", "DL"},
    {"제안요청서", "제안 요청서", "RFP"},
    {"지원사업", "지원 사업"},
    {"사업공고", "사업 공고"},
    {"정보통신", "ICT", "IT"},
    {"클라우드", "Cloud"},
    {"빅데이터", "Big Data"},
]


def _dedupe_synonyms(keywords: list[str]) -> int:
    """동의어 그룹화 후 unique 의미 단위 카운트.

    같은 그룹에 속하는 키워드는 1개로 친다.
    그룹에 없는 키워드는 그대로 1개.
    """
    if not keywords:
        return 0
    counted_groups: set[int] = set()
    standalone = 0
    for kw in keywords:
        norm = _norm(kw)
        grouped = False
        for idx, group in enumerate(_SYNONYM_GROUPS):
            if any(_norm(g) == norm for g in group):
                counted_groups.add(idx)
                grouped = True
                break
        if not grouped:
            standalone += 1
    return len(counted_groups) + standalone


def score_keyword(a: Announcement, profile: dict) -> tuple[float, list[str]]:
    """공고 본문에 회사 핵심 키워드가 얼마나 등장하는지.

    가중치 (재설계 v2 2026-05-27):
    - baseline 30 (보안 필터 통과 = 회사 영역 진입)
    - core (회사 제품/기술) × 25, cap 50 (보너스, 가끔 매칭)
    - positioning (포지셔닝 메시지) × 10, cap 20
    - 일반 사전 매칭 = log2(n+1) × 7, cap 35 (10건≈+24, 25건≈+32, 포화)
    - 동의어 그룹화로 카운트 인플레이션 차단
    - cap 100 (현실적으로 일반 사전만으로는 65점 부근이 max, core 가산 시 만점 가능)
    """
    core = profile.get("core_keywords") or []
    positioning = profile.get("positioning_keywords") or []
    blob = _blob(a)

    if not core or core == ["???"]:
        return 50.0, ["profile.yaml 의 core_keywords 미설정 — 중립 점수 50점"]

    core_hits = [k for k in core if _norm(k) in blob]
    pos_hits = [k for k in positioning if _norm(k) in blob]

    # 동의어 그룹화: keywords.yaml 표기 변형을 1 카운트로
    matched_unique_n = _dedupe_synonyms(a.matched_keywords or [])
    has_any_match = bool(core_hits or pos_hits or matched_unique_n)

    baseline = 30.0 if has_any_match else 0.0
    core_pts = min(50.0, len(core_hits) * 25.0)
    pos_pts = min(20.0, len(pos_hits) * 10.0)
    boost_pts = min(35.0, math.log2(matched_unique_n + 1) * 7.0) if matched_unique_n > 0 else 0.0

    score = min(100.0, baseline + core_pts + pos_pts + boost_pts)

    why: list[str] = []
    parts = []
    if has_any_match:
        parts.append(f"baseline {int(baseline)}")
    if core_hits:
        shown = ", ".join(core_hits[:6])
        more = f" 외 {len(core_hits) - 6}개" if len(core_hits) > 6 else ""
        why.append(f"회사 자체 키워드 {len(core_hits)}개 매칭: {shown}{more}")
        parts.append(f"core {len(core_hits)}×25 (max50) = {core_pts:.0f}")
    if pos_hits:
        why.append(f"포지셔닝 키워드 매칭: {', '.join(pos_hits[:4])}")
        parts.append(f"pos {len(pos_hits)}×10 (max20) = {pos_pts:.0f}")
    if matched_unique_n:
        raw_n = len(a.matched_keywords or [])
        dedupe_note = f" (원본 {raw_n}개 → 동의어 그룹화 {matched_unique_n}개)" if raw_n != matched_unique_n else ""
        why.append(f"보안 사전 매칭 {matched_unique_n}개{dedupe_note}: {', '.join((a.matched_keywords or [])[:6])}")
        parts.append(f"boost log2({matched_unique_n}+1)×7 (max35) = {boost_pts:.0f}")
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
