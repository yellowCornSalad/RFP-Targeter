"""기술 성숙도(TRL) 적합도. 공고 본문에 명시된 TRL 또는 키워드로 추정.

[2026-05-27 v2 재설계] 100점 일치 0건 + 정보 부족 페널티 강함 문제 해결

이전 문제:
- 회사 보유 TRL 8-9 (사업화/상용화) 만 있음 → 정부 R&D (TRL 3~7) 항상 gap 큼
- 추정 패턴 단순 ("기초연구" → TRL 3 단정)
- baseline 45 너무 박함

새 설계:
- 본문 키워드 패턴 정밀화 (TRL 2~9 모두 매칭 가능)
- 발주기관 default TRL (KISA 입찰 = TRL 7~8 가정)
- baseline 55 (정보 없으면 중간값 — 페널티 완화)
- gap 0 인접 (gap ≤1) → 95점 (이전 100점 못 받던 케이스 완화)
"""
from __future__ import annotations

import re

from rfp_targeter.db.models import Announcement


# ── TRL 키워드 추정 (사전순) ────────────────────────────────────────────
# TRL 1-2: 기초 원리 (드물게 공고로 나옴)
# TRL 3:   개념 증명, 탐색 연구
# TRL 4-5: 실험실 검증, 응용 연구, 원천 기술
# TRL 6:   파일럿, 시제품
# TRL 7:   실증, 운영 환경 시험
# TRL 8:   사업화, 시장 진입 준비
# TRL 9:   상용화, 표준화, 확산
_TRL_KEYWORDS: list[tuple[int, list[str]]] = [
    (3, ["기초연구", "기초 연구", "탐색연구", "탐색 연구", "개념증명", "개념 증명", "원리 규명"]),
    (4, ["PoC", "Proof of Concept", "시제품", "프로토타입", "랩 검증", "실험실 검증"]),
    (5, ["원천기술", "원천 기술", "응용연구", "응용 연구", "기술개발"]),
    (6, ["파일럿", "Pilot", "베타 테스트", "기능 시험"]),
    (7, ["실증", "테스트베드", "운영 환경 시험", "필드 테스트", "통합 시험"]),
    (8, ["사업화", "시장 진입", "제품화", "양산 준비"]),
    (9, ["상용화", "상용 서비스", "표준화", "확산", "보급", "인증"]),
]


def _extract_required_trl(text: str) -> tuple[int | None, str]:
    """본문에서 필요 TRL 추정.

    Returns:
        (trl, source_label) — trl 못 찾으면 (None, "")
    """
    # 1. TRL 직접 명시 (가장 신뢰)
    m = re.search(r"TRL\s*[:=]?\s*(\d)\s*[~\-]?\s*(\d)?", text, re.IGNORECASE)
    if m:
        lo = int(m.group(1))
        hi = int(m.group(2)) if m.group(2) else lo
        if 1 <= lo <= 9 and 1 <= hi <= 9:
            return (lo + hi) // 2, f"TRL {lo}~{hi} 명시"

    # 2. 키워드 기반 추정 — 가장 높은 TRL 신호 우선 (실증 > 응용 > 기초)
    # 본문에 동시 매칭되면 가장 높은 TRL (현재 사업 단계)로 추정
    best_trl = None
    best_label = ""
    for trl, kws in _TRL_KEYWORDS:
        for kw in kws:
            if kw in text:
                if best_trl is None or trl > best_trl:
                    best_trl = trl
                    best_label = f"'{kw}' 키워드 → TRL {trl}"
                break

    return best_trl, best_label


def _agency_default_trl(agency: str) -> tuple[int | None, str]:
    """발주기관별 default TRL — 키워드 추정 실패 시 fallback.

    경험적으로 KISA/NIPA 입찰공고는 실증·사업화 단계 (TRL 7~8) 가 다수.
    IITP R&D 는 응용연구 (TRL 4~5) 다수.
    MSS 사업화 지원은 TRL 8.
    """
    ag = (agency or "").strip()
    if "KISA" in ag or "한국인터넷진흥원" in ag:
        return 7, "KISA 입찰 default (실증·사업화)"
    if "NIPA" in ag or "정보통신산업진흥원" in ag:
        return 7, "NIPA default (실증·사업화)"
    if "IITP" in ag or "정보통신기획평가원" in ag:
        return 5, "IITP default (응용연구)"
    if "중소벤처기업부" in ag or "MSS" in ag:
        return 8, "MSS default (사업화)"
    return None, ""


def score_trl(a: Announcement, profile: dict) -> tuple[float, list[str]]:
    text = " ".join(filter(None, [a.title, a.summary, a.body]))

    required, source = _extract_required_trl(text)
    if required is None:
        # 발주기관 default 시도
        required, source = _agency_default_trl(a.agency or "")

    techs = profile.get("technologies") or []
    own_trls = sorted({t["trl"] for t in techs if isinstance(t.get("trl"), int)})

    if required is None:
        return 55.0, [
            "공고에서 TRL 요구치 추정 불가 + 발주기관 default 없음",
            "📐 산정: 정보 부족 → **55점** (중간값)",
        ]

    if not own_trls:
        return 55.0, [
            f"공고 요구 TRL≈{required} ({source}) — 회사 보유 TRL 데이터 없음",
            "📐 산정: 회사 TRL 미설정 → **55점**",
        ]

    closest_gap = min(abs(t - required) for t in own_trls)

    # ── gap 별 점수 (v2 tuned: TRL 100점 인플레이션 차단) ──
    # gap 0 흔하니 (KISA 입찰=TRL 7 + 회사 TRL 8 → gap 1) 한 단계씩 낮춤
    if closest_gap == 0:
        score = 95.0   # gap 0 = 정확 일치 (드문 케이스)
    elif closest_gap == 1:
        score = 85.0   # gap 1 = 인접 단계 (KISA·NIPA 대다수)
    elif closest_gap == 2:
        score = 70.0
    elif closest_gap == 3:
        score = 55.0
    else:
        score = 40.0

    return score, [
        f"공고 요구 TRL ≈ {required} ({source})",
        f"회사 보유 TRL: {own_trls} — 최소 gap = {closest_gap}",
        f"📐 산정: gap {closest_gap} → **{score:.0f}점**",
    ]
