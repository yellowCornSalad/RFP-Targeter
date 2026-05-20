"""예산 적합도. sweet spot 근처면 100점, 멀어질수록 감점."""
from __future__ import annotations

from rfp_targeter.db.models import Announcement


def score_budget(a: Announcement, profile: dict) -> tuple[float, list[str]]:
    rng = profile.get("budget_range") or {}
    if a.budget_mw is None:
        return 50.0, ["공고에 예산 정보 없음 — 중립 점수"]

    lo = rng.get("min", 0)
    hi = rng.get("max", 99999)
    s_lo = rng.get("sweet_spot_min", lo)
    s_hi = rng.get("sweet_spot_max", hi)
    bud = a.budget_mw

    if s_lo <= bud <= s_hi:
        return 100.0, [f"예산 {bud}백만원 — sweet spot({s_lo}~{s_hi}) 내"]
    if bud < lo:
        return 20.0, [f"예산 {bud}백만원 — 너무 작음 (회사 최소 {lo})"]
    if bud > hi:
        return 25.0, [f"예산 {bud}백만원 — 너무 큼 (회사 최대 {hi}, 단독 수행 부담)"]

    # 회사 범위 내지만 sweet spot 밖 → 선형 감점
    if bud < s_lo:
        ratio = (bud - lo) / max(s_lo - lo, 1)
        score = 60 + ratio * 40
    else:  # bud > s_hi
        ratio = (hi - bud) / max(hi - s_hi, 1)
        score = 60 + ratio * 40
    return round(score, 1), [f"예산 {bud}백만원 — sweet spot 근접"]
