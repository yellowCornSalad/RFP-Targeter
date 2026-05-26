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


# Boilerplate 컨텍스트 — 정부 공고 본문 공통 문구에서 잘못 매칭되는 케이스.
# 키워드 → (boilerplate 패턴, 진짜 사업 신호 패턴)
# boilerplate 만 있고 진짜 신호 없으면 매칭에서 제거.
_BOILERPLATE_CONTEXT = {
    "마이데이터": {
        # "공공마이데이터 정보제공 동의" = 행정서류 자동 출력 안내, 사업 본질과 무관
        "boilerplate": ["공공마이데이터"],
        # 진짜 마이데이터 사업 신호 — 이 표현이 있으면 boilerplate 무시
        "real_signals": ["마이데이터사업", "마이데이터서비스", "마이데이터인프라",
                        "마이데이터중계", "민간마이데이터", "마이데이터플랫폼",
                        "마이데이터실증", "마이데이터정책"],
    },
    "MyData": {
        "boilerplate": [],
        "real_signals": ["MyData 사업", "MyData Service"],
    },
    "자금세탁": {
        # "자금세탁방지 가이드라인" = 자격요건 법규 인용, 사업 본질과 무관
        "boilerplate": ["자금세탁방지", "자금세탁 방지"],
        # 진짜 자금세탁 관련 사업
        "real_signals": ["자금세탁방지시스템", "자금세탁탐지", "AML 시스템"],
    },
    "AML": {
        "boilerplate": [],
        "real_signals": ["AML 시스템", "AML 솔루션", "AML 플랫폼"],
    },
    "KYC": {
        "boilerplate": [],
        "real_signals": ["KYC 시스템", "KYC 솔루션", "eKYC"],
    },
}


def _filter_boilerplate(matched: list[str], haystack: str) -> list[str]:
    """매칭 키워드 중 boilerplate-only 매칭은 제거.

    예: '마이데이터' 매칭됐는데 본문에 '공공마이데이터' 만 있고 진짜 사업 신호
    ('마이데이터사업/인프라/중계' 등) 없으면 매칭 리스트에서 제거.
    """
    out = []
    for kw in matched:
        ctx = _BOILERPLATE_CONTEXT.get(kw)
        if not ctx:
            out.append(kw)
            continue
        has_boilerplate = any(_normalize(p) in haystack for p in ctx["boilerplate"])
        has_real = any(_normalize(p) in haystack for p in ctx["real_signals"])
        if has_boilerplate and not has_real:
            continue  # 거짓 양성 — 매칭 제거
        out.append(kw)
    return out


class SecurityFilter:
    def __init__(self, cfg: dict | None = None) -> None:
        cfg = cfg or keywords()
        self._must_any = cfg.get("must_any", [])
        self._boost = cfg.get("boost", [])
        self._exclude = cfg.get("exclude", [])
        # exclude_strict — 무조건 탈락 (must_any 매칭 무관). 박사후/장학금 등
        # 회사가 절대 신청 불가능한 명확한 잡음만 등재.
        self._exclude_strict = cfg.get("exclude_strict", [])
        self._must_any_agency = cfg.get("must_any_agency", [])

    def check(self, *texts: str | None, agency: str | None = None) -> FilterResult:
        """제목·요약·본문 등 여러 문자열을 한 번에 검사.

        agency가 회사 본업 부서 화이트리스트에 일치하면 키워드 매칭 약해도 통과
        (통합 공고 누락 방지).

        🔧 2026-05-26 수정: exclude 규칙 너무 강했음.
        "정보보호 해외인증제도" 같은 본업 공고도 본문 어딘가 '물리보안' 단어
        하나 나오면 통째로 탈락하는 버그. 이제는 must_any 매칭이 1+ 있으면
        exclude 무시 (= 보안 키워드 명백한 공고는 통과 보장).
        매칭 0개 + exclude 있을 때만 탈락 (현행 유지).
        """
        haystack = _normalize(" ".join(t for t in texts if t))

        # exclude_strict — 무조건 탈락 (회사 신청 불가능한 명확한 잡음)
        excluded_hard = [k for k in self._exclude_strict if _normalize(k) in haystack]
        if excluded_hard:
            return FilterResult(False, [], [], excluded_hard)

        matched = [k for k in self._must_any if _normalize(k) in haystack]
        boosted = [k for k in self._boost if _normalize(k) in haystack]
        excluded = [k for k in self._exclude if _normalize(k) in haystack]

        # 🔧 boilerplate 매칭 제거 — '공공마이데이터', '자금세탁방지' 같이 정부 공고
        # 공통 안내 문구에서 잘못 매칭된 키워드 제거. 진짜 사업 신호 있으면 유지.
        matched = _filter_boilerplate(matched, haystack)
        boosted = _filter_boilerplate(boosted, haystack)

        # 🔥 변경: must_any 매칭 0건일 때만 일반 exclude 의해 탈락.
        #     매칭 1+ 있으면 보안 영역 명백 → 일반 exclude 무시하고 통과.
        if not matched and excluded:
            return FilterResult(False, [], [], excluded)

        # 부서명 자동 통과 (정확 매칭 — 부서명은 enum이라 fuzzy 없음)
        agency_match = None
        if agency and not matched:
            agency_norm = _normalize(agency)
            for dept in self._must_any_agency:
                if _normalize(dept) == agency_norm:
                    agency_match = dept
                    matched = [f"[부서] {dept}"]   # 매칭 표시
                    break

        return FilterResult(
            passed=bool(matched) or bool(agency_match),
            matched=matched,
            boost_matched=boosted,
            excluded_by=[],
        )
