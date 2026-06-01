"""공고 본문 LLM 요약 — 카드에 표시할 1~2문장 핵심 요약.

설계:
- claude-haiku-4-5 (저렴·빠름) 사용. 카드 표시용이므로 품질보다 속도·비용 우선
- 1건당 ~$0.001 예상 (입력 ~3000자, 출력 ~150자)
- DB ai_summary 컬럼에 캐시 — 1회 생성 후 재사용
- hallucination 방지: "본문에 있는 사실만, 추정·해석 X" 시스템 프롬프트

사용:
    from rfp_targeter.drafter.summarizer import summarize_announcement
    summary = summarize_announcement(title, body)  # 실패 시 None
"""
from __future__ import annotations

import logging

from rfp_targeter.config import secrets

log = logging.getLogger(__name__)

_SUMMARY_MODEL = "claude-haiku-4-5"
_SYSTEM_PROMPT = """당신은 정부 R&D 공고의 핵심을 짧게 요약하는 도우미입니다.

규칙:
1. 본문에 명시된 사실만 사용. 추정·해석·외부 지식 절대 X
2. 1~2문장 (총 80~140자 내외). 너무 짧으면 안 됨
3. "사업 목적 / 모집 대상 / 핵심 활동" 중 가장 두드러진 것 한두 가지
4. 정부 R&D 표준 문구 ("기획재정부 계약예규", "협상에 의한 계약체결기준" 등)는 제외
5. 마침표로 끝. 따옴표·이모지·마크다운 X
6. 평문 한 줄로 반환. 머리말("요약:", "이 공고는") 금지

예시:
- AI 기반 차세대 보안 제품 상용화 단계 기업의 회계정산 용역으로, 보조금 집행 적정성 검토와 정산보고서 작성을 지원합니다.
- 블록체인 응용서비스 API 개발 자금을 모집하는 사업으로, 기업당 최대 1억원 지원 및 6개월 개발 기간을 제공합니다."""


def summarize_announcement(title: str, body: str, max_chars: int = 3000) -> str | None:
    """본문에서 카드 표시용 1~2문장 요약 생성.

    실패 시 None — 호출자가 facts/excerpt 폴백 사용.
    """
    if not body or len(body) < 100:
        return None

    try:
        import anthropic
    except ImportError:
        log.debug("anthropic SDK 미설치 — 요약 건너뜀")
        return None

    sec = secrets() or {}
    api_key = (sec.get("anthropic") or {}).get("api_key")
    if not api_key or api_key in ("???", "PASTE_YOUR_KEY"):
        log.debug("anthropic api_key 미설정 — 요약 건너뜀")
        return None

    # 본문 너무 길면 잘라서 비용 절감 (앞부분에 핵심 정보 있음)
    body_short = body[:max_chars]

    try:
        client = anthropic.Anthropic(api_key=api_key)
        msg = client.messages.create(
            model=_SUMMARY_MODEL,
            max_tokens=200,
            system=_SYSTEM_PROMPT,
            messages=[{
                "role": "user",
                "content": f"제목: {title}\n\n본문:\n{body_short}\n\n위 공고의 핵심을 1~2문장으로 요약."
            }],
        )
        text = "".join(b.text for b in msg.content if hasattr(b, "text")).strip()
        # 후처리: 따옴표/마크다운 제거
        text = text.strip('"\'`').strip()
        if text.startswith("- "):
            text = text[2:]
        if len(text) < 20 or len(text) > 300:
            return None
        return text
    except Exception as e:
        # 진단용: anthropic APIError 의 status_code + body(message 포함) 명시 로깅.
        # (str(e) 가 message 직전에 잘리는 케이스 대비)
        log.warning(
            "summarize fail: %r | status=%s | body=%r",
            e, getattr(e, "status_code", "?"), getattr(e, "body", None),
        )
        return None
