"""점수 산정 통합 엔진."""
from __future__ import annotations

from rfp_targeter.config import profile, settings
from rfp_targeter.db.models import Announcement, Score
from rfp_targeter.scoring.budget import score_budget
from rfp_targeter.scoring.competitor import score_competitor
from rfp_targeter.scoring.consortium import score_consortium
from rfp_targeter.scoring.keyword import score_keyword, score_theme_fit
from rfp_targeter.scoring.trl import score_trl


def compute_score(a: Announcement) -> Score:
    p = profile()
    weights = settings()["scoring_weights"]

    kw, kw_why = score_keyword(a, p)
    bg, bg_why = score_budget(a, p)
    cs, cs_why = score_consortium(a, p)
    cp, cp_why = score_competitor(a, p)
    tr, tr_why = score_trl(a, p)

    total = (
        kw * weights["keyword"]
        + bg * weights["budget"]
        + cs * weights["consortium"]
        + cp * weights["competitor"]
        + tr * weights["trl"]
    )

    theme, theme_why = score_theme_fit(a, p)

    # theme_fit 보너스: 회사 테마와 강하게 매칭되면 가산
    if theme >= 80:
        total = min(100.0, total + 10)
    elif theme >= 60:
        total = min(100.0, total + 5)
    elif theme < 30:
        total = max(0.0, total - 5)

    rationale = {
        "keyword": kw_why,
        "budget": bg_why,
        "consortium": cs_why,
        "competitor": cp_why,
        "trl": tr_why,
        "theme_fit": theme_why,
    }

    return Score(
        announcement_id=a.id,
        keyword_score=round(kw, 1),
        budget_score=round(bg, 1),
        consortium_score=round(cs, 1),
        competitor_score=round(cp, 1),
        trl_score=round(tr, 1),
        total_score=round(total, 1),
        theme_fit=round(theme, 1),
        rationale=rationale,
    )
