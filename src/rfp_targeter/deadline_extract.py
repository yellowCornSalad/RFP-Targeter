"""LLM 마감일 추출 — 공고 본문에서 '신청자(지원자) 제출 마감일'만 정확히 뽑아낸다.

배경 (2026-06-02 사용자 요청 'B 확신으로'):
- IITP 등 data.go.kr API 공고는 deadline_at 가 NULL → '등록 60일내'라는 추정으로만 활성 판단.
- 본문엔 "신청기간 ~ YYYY.MM.DD" 가 있으나, 사업기간·공고기간·이의신청·선정결과 등
  여러 날짜가 섞여 정규식으론 오추출 위험 → LLM 이 '신청 제출 마감'만 골라 '확신'으로 전환.

원칙: 본문 근거로만. 추정·할루시네이션 금지. 신청 마감 명시 없으면/결과 공고면 null.

사용:
    from rfp_targeter.deadline_extract import extract_deadline
    d = extract_deadline(title, body, posted_at="2026-06-01")  # "2026-06-09" 또는 None
"""
from __future__ import annotations

import json
import logging
import re
from datetime import date

from rfp_targeter.config import secrets

log = logging.getLogger(__name__)

_MODEL = "claude-haiku-4-5"

_SYSTEM = """당신은 정부 R&D/사업 공고에서 '신청자(지원 기업)가 서류를 제출해야 하는 최종 마감일' 하나만 정확히 추출하는 추출기입니다.
반드시 본문 근거로만 판단하세요. 추정·외부지식·할루시네이션 절대 금지.

[뽑을 것] 신청/접수/공모/제출 '마감일'.
  "접수기간 ~ X", "신청기간 ~ X", "X까지 접수/신청", "공고기간 ~ X" 의 끝 날짜 X.
  여러 신청 마감(예: 연구책임자 신청 / 주관기관 검토 마감)이 있으면, 지원 기업이 제출하는 '가장 이른' 마감을 고르세요.

[절대 제외 — 이건 마감일이 아님]
  · 사업기간·협약기간·수행기간 종료일 (예: "사업기간 ~ 12월 31일")
  · 공고일/등록일/사업 시작일
  · 선정결과 발표일·평가 예정일·설명회 일자
  · 이의신청 마감일

[null 로 둘 것]
  · 신청을 받지 않는 공고: 선정결과 공고, 심의예정 공고, 결과 안내, 지정/변경 공고
  · 본문에 신청 마감일이 명시되지 않은 경우

[연도] 날짜에 연도가 없으면("6월 9일") [공고 등록일]의 연도를 사용.

출력은 JSON 한 줄만. 다른 텍스트·코드펜스 금지:
{"deadline": "YYYY-MM-DD" 또는 null, "reason": "<한 줄 근거, 본문 표현 인용>"}"""

_KW = re.compile(r"(신청\s*기간|접수\s*기간|접수\s*마감|신청\s*마감|공모\s*기간|모집\s*기간|제출\s*마감|까지\s*접수)")


def _excerpt(body: str, max_chars: int) -> str:
    """본문에서 마감 관련 부분을 우선 포함한 발췌 (긴 본문 대비)."""
    if len(body) <= max_chars:
        return body
    head = body[:3000]
    m = _KW.search(body)
    if m and m.start() > 2500:
        w = body[max(0, m.start() - 500): m.start() + 2500]
        return (head + "\n…(중략)…\n" + w)[:max_chars]
    return body[:max_chars]


def extract_deadline(title: str, body: str, posted_at: str | None = None,
                     max_chars: int = 7000) -> str | None:
    """본문에서 신청 제출 마감일(YYYY-MM-DD) 추출. 없으면/결과공고면/실패면 None."""
    if not body or len(body) < 100:
        return None
    try:
        import anthropic
    except ImportError:
        return None
    sec = secrets() or {}
    api_key = (sec.get("anthropic") or {}).get("api_key")
    if not api_key or api_key in ("???", "PASTE_YOUR_KEY"):
        log.debug("anthropic api_key 미설정 — deadline 추출 건너뜀")
        return None

    user = (
        f"[공고 등록일] {posted_at or '미상'}\n\n"
        f"[공고 제목]\n{title}\n\n"
        f"[공고 본문]\n{_excerpt(body, max_chars)}\n\n"
        "위에서 신청자 제출 마감일을 추출해 JSON 으로만 답하세요."
    )
    try:
        client = anthropic.Anthropic(api_key=api_key)
        msg = client.messages.create(
            model=_MODEL,
            max_tokens=200,
            system=_SYSTEM,
            messages=[{"role": "user", "content": user}],
        )
        text = "".join(b.text for b in msg.content if hasattr(b, "text")).strip()
        text = text.strip("`").strip()
        if text[:4].lower() == "json":
            text = text[4:].strip()
        i, j = text.find("{"), text.rfind("}")
        if i < 0 or j < 0:
            return None
        data = json.loads(text[i:j + 1])
        dl = data.get("deadline")
        if not dl or not isinstance(dl, str):
            return None
        m = re.match(r"(\d{4})-(\d{1,2})-(\d{1,2})", dl.strip())
        if not m:
            return None
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        # 유효성 + 상식 범위 (2024~2030) 검증 — 오추출 방어
        try:
            date(y, mo, d)
        except ValueError:
            return None
        if not (2024 <= y <= 2030):
            return None
        return f"{y:04d}-{mo:02d}-{d:02d}"
    except Exception as e:
        log.debug("deadline 추출 실패: %s", e)
        return None
