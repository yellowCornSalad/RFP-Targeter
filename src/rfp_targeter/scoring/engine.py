"""점수 산정 통합 엔진.

[2026-05-27] consortium → eligibility 의미 교체.
DB 컬럼 (consortium_score) 은 legacy 유지 — 마이그레이션 회피.
실제 채워지는 값은 score_eligibility() 결과.
"""
from __future__ import annotations

from rfp_targeter.config import profile, settings
from rfp_targeter.db.models import Announcement, Score
from rfp_targeter.scoring.budget import score_budget
from rfp_targeter.scoring.competitor import score_competitor
from rfp_targeter.scoring.eligibility import score_eligibility
from rfp_targeter.scoring.keyword import score_keyword, score_theme_fit
from rfp_targeter.scoring.trl import score_trl


def compute_score(a: Announcement) -> Score:
    p = profile()
    weights = settings()["scoring_weights"]

    kw, kw_why = score_keyword(a, p)
    bg, bg_why = score_budget(a, p)
    el, el_why = score_eligibility(a, p)   # 이전 consortium 자리 → 자격 적합도
    cp, cp_why = score_competitor(a, p)
    tr, tr_why = score_trl(a, p)

    # weights 키: "eligibility" (신규) 우선, 폴백으로 "consortium" (legacy 호환)
    el_weight = weights.get("eligibility", weights.get("consortium", 0.20))

    total = (
        kw * weights["keyword"]
        + bg * weights["budget"]
        + el * el_weight
        + cp * weights["competitor"]
        + tr * weights["trl"]
    )

    theme, theme_why = score_theme_fit(a, p)

    # theme_fit 보너스 — 회사 본업 매칭이 강하면 변별력 있는 가산
    # 이전: ≥80 +10 / ≥60 +5 / <30 -5 (TOP도 70점에 못 미침)
    # 변경: ≥90 +20 / ≥80 +12 / ≥60 +6 / <30 -10
    if theme >= 90:
        total = min(100.0, total + 20)
    elif theme >= 80:
        total = min(100.0, total + 12)
    elif theme >= 60:
        total = min(100.0, total + 6)
    elif theme < 30:
        total = max(0.0, total - 10)

    rationale = {
        "keyword": kw_why,
        "budget": bg_why,
        "eligibility": el_why,   # 이전 "consortium" — UI 호환 위해 key 변경
        "competitor": cp_why,
        "trl": tr_why,
        "theme_fit": theme_why,
    }

    return Score(
        announcement_id=a.id,
        keyword_score=round(kw, 1),
        budget_score=round(bg, 1),
        consortium_score=round(el, 1),   # DB 컬럼 legacy: 실제 값은 eligibility
        competitor_score=round(cp, 1),
        trl_score=round(tr, 1),
        total_score=round(total, 1),
        theme_fit=round(theme, 1),
        rationale=rationale,
    )
