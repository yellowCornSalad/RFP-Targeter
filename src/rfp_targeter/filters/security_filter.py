"""보안 키워드 1차 필터.

- keywords.yaml 의 must_any 중 하나라도 매칭되면 통과
- exclude 키워드가 있으면 제거
- 매칭된 키워드 목록을 반환 (점수 산정에서 재활용)
"""
from __future__ import annotations

from dataclasses import dataclass

from rfp_targeter.config import keywords


@dataclass
class FilterResult:
    passed: bool
    matched: list[str]
    boost_matched: list[str]
    excluded_by: list[str]


def _normalize(text: str) -> str:
    return text.replace(" ", "").lower()


class SecurityFilter:
    def __init__(self, cfg: dict | None = None) -> None:
        cfg = cfg or keywords()
        self._must_any = cfg.get("must_any", [])
        self._boost = cfg.get("boost", [])
        self._exclude = cfg.get("exclude", [])

    def check(self, *texts: str | None) -> FilterResult:
        """제목·요약·본문 등 여러 문자열을 한 번에 검사."""
        haystack = _normalize(" ".join(t for t in texts if t))

        excluded = [k for k in self._exclude if _normalize(k) in haystack]
        if excluded:
            return FilterResult(False, [], [], excluded)

        matched = [k for k in self._must_any if _normalize(k) in haystack]
        boosted = [k for k in self._boost if _normalize(k) in haystack]

        return FilterResult(
            passed=bool(matched),
            matched=matched,
            boost_matched=boosted,
            excluded_by=[],
        )
