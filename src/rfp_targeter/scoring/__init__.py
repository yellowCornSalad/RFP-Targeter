"""점수 산정 엔진.

5개 지표 (0~100):
- keyword:    공고 키워드 ↔ 회사 핵심 키워드 매칭도
- budget:     공고 예산 ↔ 회사 적정 범위 적합도
- consortium: 컨소시엄 구성 부담 (낮을수록 좋음 → 점수 높음)
- competitor: 경쟁 상황 (경쟁 적을수록 점수 높음)
- trl:        요구 기술 성숙도 ↔ 회사 보유 TRL 적합도

theme_fit (별도 지표): 회사 테마와의 적합도. UI에서 따로 노출.

각 산정기는 (score, rationale_list) 반환.
"""
from __future__ import annotations

from rfp_targeter.scoring.engine import compute_score

__all__ = ["compute_score"]
