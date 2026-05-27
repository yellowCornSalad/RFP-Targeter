"""예산 적합도 (재설계 v2 2026-05-27).

회사 정책 (사용자 확정):
- 연간 1억(100백만원) 이상은 긍정적으로 본다 (이전 200=2억 min → 100=1억으로 완화)
- 너무 큰 예산도 부정 X — 컨소시엄으로 분담 가능
- 5~40억 sweet spot 만 100점 (OFFen 단독 수행 적정)

공식:
  budget_mw NULL                     →  35점 (정보 부족 페널티)
  < 100 (1억 미만)                   →  25~50점 선형 (작음)
  100~499 (1~5억 긍정 영역)          →  70~95점 선형
  500~4000 (5~40억 sweet spot)       →  100점
  4001~10000 (40~100억 대형)         →  90~100점 선형 (살짝 감점)
  > 10000 (100억+ 초대형)            →  80~90점 (컨소시엄 가능 — 부정 안 함)
"""
from __future__ import annotations

from rfp_targeter.db.models import Announcement


def score_budget(a: Announcement, profile: dict) -> tuple[float, list[str]]:
    """예산 점수 — 회사 정책 기반 (1억+ 긍정, 큰 예산 컨소시엄 OK)."""
    if a.budget_mw is None:
        return 35.0, [
            "공고에 예산 정보 없음 — 정보 부족 페널티",
            "📐 산정: 정보없음 → **35점**",
        ]

    bud = a.budget_mw
    won_eok = bud / 100  # 백만원 → 억원

    # ── 1. 1억 미만: 너무 작음 (회사 ROI 낮음) ──
    if bud < 100:
        # 0 → 25, 100 → 50 선형
        score = round(25 + (bud / 100) * 25, 1)
        return score, [
            f"예산 {won_eok:.1f}억 ({bud}백만원) — 1억 미만 (회사 ROI 낮음)",
            f"📐 산정: 1억 미만 선형 → **{score:.0f}점**",
        ]

    # ── 2. 1~5억: 긍정 영역 (1억+ 부터 회사 긍정 평가) ──
    if bud < 500:
        # 100 → 70, 500 → 95 선형 (sweet spot 진입 직전까지)
        score = round(70 + (bud - 100) / 400 * 25, 1)
        return score, [
            f"예산 {won_eok:.1f}억 ({bud}백만원) — 1~5억 긍정 영역",
            f"📐 산정: 1~5억 선형 (1억+ 회사 긍정) → **{score:.0f}점**",
        ]

    # ── 3. 5~40억: SWEET SPOT (OFFen 단독 수행 적정) ──
    if bud <= 4000:
        return 100.0, [
            f"예산 {won_eok:.1f}억 ({bud}백만원) — sweet spot (5~40억 단독 적정)",
            "📐 산정: sweet spot 적중 → **100점**",
        ]

    # ── 4. 40~100억: 대형 (컨소시엄 검토) ──
    if bud <= 10000:
        # 4000 → 100, 10000 → 90 선형 (살짝 감점)
        score = round(100 - (bud - 4000) / 6000 * 10, 1)
        return score, [
            f"예산 {won_eok:.1f}억 ({bud}백만원) — 40~100억 대형 (컨소시엄 검토)",
            f"📐 산정: 40~100억 선형 → **{score:.0f}점**",
        ]

    # ── 5. 100억+: 초대형 (컨소시엄 필수, 그러나 부정 X) ──
    # 10000 → 90, 30000 → 85, 100000+ → 80 (점진 감점, floor 80)
    score = round(max(80.0, 90 - (bud - 10000) / 10000 * 2), 1)
    return score, [
        f"예산 {won_eok:.1f}억 ({bud}백만원) — 100억+ 초대형 (컨소시엄 필수)",
        f"📐 산정: 100억+ 점진 감점 (컨소시엄 가능, 부정 X) → **{score:.0f}점**",
    ]
