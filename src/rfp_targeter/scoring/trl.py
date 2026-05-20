"""기술 성숙도(TRL) 적합도. 공고 본문에 명시된 TRL 또는 키워드로 추정."""
from __future__ import annotations

import re

from rfp_targeter.db.models import Announcement


def _extract_required_trl(text: str) -> int | None:
    m = re.search(r"TRL\s*[:=]?\s*(\d)\s*[~\-]?\s*(\d)?", text, re.IGNORECASE)
    if m:
        lo = int(m.group(1))
        hi = int(m.group(2)) if m.group(2) else lo
        return (lo + hi) // 2
    if any(w in text for w in ["기초연구", "탐색연구"]):
        return 3
    if any(w in text for w in ["실증", "사업화", "상용화", "제품화"]):
        return 7
    if any(w in text for w in ["원천기술", "응용연구"]):
        return 5
    return None


def score_trl(a: Announcement, profile: dict) -> tuple[float, list[str]]:
    text = " ".join(filter(None, [a.title, a.summary, a.body]))
    required = _extract_required_trl(text)

    techs = profile.get("technologies") or []
    own_trls = [t["trl"] for t in techs if isinstance(t.get("trl"), int)]

    if required is None:
        return 60.0, ["공고에서 TRL 요구치 추정 불가 — 중립 점수"]

    if not own_trls:
        return 50.0, [f"공고 요구 TRL≈{required} — 회사 보유 TRL 데이터 없음"]

    closest_gap = min(abs(t - required) for t in own_trls)
    if closest_gap == 0:
        return 100.0, [f"공고 TRL {required} = 회사 보유 기술과 일치"]
    if closest_gap == 1:
        return 85.0, [f"공고 TRL {required} ↔ 회사 {own_trls} (gap 1)"]
    if closest_gap == 2:
        return 65.0, [f"공고 TRL {required} ↔ 회사 {own_trls} (gap 2)"]
    return 40.0, [f"공고 TRL {required} ↔ 회사 {own_trls} (gap {closest_gap}, 갭 큼)"]
