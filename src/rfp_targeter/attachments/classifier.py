"""첨부 파일 자동 분류 — 파일명 패턴 기반.

공고에 보통 첨부되는 파일 종류:
- 공고문(notice): 사업 안내·공고 본문
- 양식(form): 신청서·계획서·서식 — 사용자가 작성해 제출하는 것
- 평가표(eval): 평가 기준·심사표
- 참고(reference): Q&A·FAQ·참고 자료
- 기타(other): 분류 불명
"""
from __future__ import annotations

import re

# 우선순위 순으로 평가 (form > notice > eval > reference)
_FORM_PATTERNS = [
    "신청서", "신청양식", "사업계획서", "연구개발계획서", "사업 계획서",
    "지원서", "양식", "서식", "별지", "RFP", "사업제안서", "제안서양식",
    "신청 양식", "계획서 양식", "Application", "Form",
]
_NOTICE_PATTERNS = [
    "공고문", "공고", "안내문", "안내", "사업안내", "사업 안내", "사업공고",
    "모집 공고", "모집공고", "Notice", "Announce",
]
_EVAL_PATTERNS = [
    "평가표", "평가기준", "심사표", "심사기준", "선정기준", "평가 기준",
    "심사 기준", "채점", "배점", "Evaluation",
]
_REFERENCE_PATTERNS = [
    "Q&A", "QnA", "FAQ", "Q & A", "참고", "별첨 참고", "FAQ 안내",
    "사례", "예시", "Reference",
]

_CATEGORY_LABELS = {
    "form": "📝 양식 (작성·제출)",
    "notice": "📄 공고문",
    "eval": "📊 평가표·심사기준",
    "reference": "📎 참고 자료",
    "other": "📦 기타",
}


def classify(name: str) -> str:
    """파일명 → category (form/notice/eval/reference/other)."""
    if not name:
        return "other"
    lower = name.lower()
    # form 이 가장 강한 신호 (작성해 제출해야 함 — 사용자에게 가장 중요)
    if any(p.lower() in lower for p in _FORM_PATTERNS):
        return "form"
    if any(p.lower() in lower for p in _EVAL_PATTERNS):
        return "eval"
    if any(p.lower() in lower for p in _NOTICE_PATTERNS):
        return "notice"
    if any(p.lower() in lower for p in _REFERENCE_PATTERNS):
        return "reference"
    return "other"


def label(category: str) -> str:
    return _CATEGORY_LABELS.get(category, "📦 기타")


def priority(category: str) -> int:
    """텍스트 추출 우선순위 — 낮을수록 먼저."""
    return {"notice": 0, "form": 1, "eval": 2, "reference": 3, "other": 5}.get(category, 9)


def group_by_category(attachments: list[dict]) -> dict[str, list[dict]]:
    """첨부 리스트를 분류별로 그룹화."""
    groups: dict[str, list[dict]] = {}
    for att in attachments:
        cat = att.get("category") or classify(att.get("name", ""))
        groups.setdefault(cat, []).append(att)
    return groups
