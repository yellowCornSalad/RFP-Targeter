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


def compute_score(a: Announcement, llm: dict | None = None) -> Score:
    """5축 점수 + 총점. llm(도메인 적합성·TRL 본문 판단)이 있으면 반영.

    llm = {"relevance": "high|medium|low|none", "trl": int|None, ...} (assess_contents).
    크롤 시점엔 llm=None (기존 키워드 기반). build_summaries 가 평가 후 재계산.
    """
    p = profile()
    weights = settings()["scoring_weights"]

    kw, kw_why = score_keyword(a, p)
    bg, bg_why = score_budget(a, p)
    el, el_why = score_eligibility(a, p)   # 이전 consortium 자리 → 자격 적합도
    cp, cp_why = score_competitor(a, p)
    tr, tr_why = score_trl(a, p, llm=llm)   # 🤖 LLM TRL 판단 우선

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

    # 🤖 LLM 도메인 적합성 배율 [사용자 결정 2026-06-01 — 강한 배율]
    # 키워드만 맞고 실제 무관한 공고(조사/교육/제조 용역 등)를 총점에서 하위로.
    # none ×0.5 / low ×0.75 / medium ×0.92 / high ×1.0. 미평가(llm None)면 미적용.
    rel = (llm or {}).get("relevance")
    rel_mult = {"high": 1.0, "medium": 0.92, "low": 0.75, "none": 0.5}.get(rel)
    llm_why = []
    if rel_mult is not None:
        _before = total
        total = round(total * rel_mult, 1)
        if rel_mult != 1.0:
            llm_why.append(
                f"🤖 LLM 도메인 적합성 '{rel}' → 총점 ×{rel_mult} ({_before:.0f}→{total:.0f})"
            )
        else:
            llm_why.append(f"🤖 LLM 도메인 적합성 '{rel}' → 감점 없음")

    rationale = {
        "keyword": kw_why,
        "budget": bg_why,
        "eligibility": el_why,   # 이전 "consortium" — UI 호환 위해 key 변경
        "competitor": cp_why,
        "trl": tr_why,
        "theme_fit": theme_why,
    }
    if llm_why:
        rationale["llm_relevance"] = llm_why

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
