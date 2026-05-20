"""Anthropic Claude API로 /rfp 스킬을 활용한 1차 RFP 초안 자동 작성.

설계 (2026-05 기준, claude-api 스킬 가이드 따름):
- 모델: claude-opus-4-7 (최신 최강. 1M context, 128K max output)
- Thinking: adaptive (4.7은 기본 OFF — 명시적 ON)
- Effort: xhigh (4.7에서 새로 추가, agentic/coding 최적)
- max_tokens: 32000 (thinking + 출력 여유)
- Streaming: 필수 (max_tokens 크면 SDK 차단)
- Prompt caching: 시스템(rfp.md, ~3500토큰)에 ephemeral 캐시
  - 5분 내 반복 호출 시 입력 90% 절감
- Structured output: 미사용
  - 출력이 자유 마크다운(브레인스토밍 카드 + 6목차)이라 json_schema 제약 부적합

시스템 프롬프트: ~/.claude/commands/rfp.md (사용자가 만든 /rfp 스킬 정의)
응답: 브레인스토밍 카드 3~5개 + 1번 자동 선택 + 표준 6목차 뼈대
"""
from __future__ import annotations

import logging
from pathlib import Path

from rfp_targeter.config import secrets

log = logging.getLogger(__name__)

# /rfp 스킬 정의 위치 후보 (OS별)
_RFP_SKILL_PATHS = [
    Path.home() / ".claude" / "commands" / "rfp.md",
    Path.home() / ".claude" / "skills" / "rfp" / "SKILL.md",
    Path.home() / ".config" / "claude" / "commands" / "rfp.md",
]

# 기본값 — secrets.yaml 의 anthropic 섹션에서 override 가능
DEFAULT_MODEL = "claude-opus-4-7"
DEFAULT_EFFORT = "xhigh"          # Opus 4.7 전용 레벨 (그 외 모델은 자동으로 "high"로 폴백)
DEFAULT_MAX_TOKENS = 32000        # thinking + 출력 충분 (1M context 중 미미)


# 가격표 ($/1M tokens, 2026-05 기준)
_PRICING = {
    "claude-opus-4-7":  {"input": 5.00, "output": 25.00, "cache_write": 6.25, "cache_read": 0.50},
    "claude-opus-4-6":  {"input": 5.00, "output": 25.00, "cache_write": 6.25, "cache_read": 0.50},
    "claude-sonnet-4-6":{"input": 3.00, "output": 15.00, "cache_write": 3.75, "cache_read": 0.30},
    "claude-haiku-4-5": {"input": 1.00, "output":  5.00, "cache_write": 1.25, "cache_read": 0.10},
}


def _load_rfp_skill() -> str | None:
    for p in _RFP_SKILL_PATHS:
        if p.exists():
            return p.read_text(encoding="utf-8")
    return None


def is_available() -> tuple[bool, str]:
    """LLM 사용 가능 여부 + 사유 메시지 반환."""
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return False, "anthropic SDK 미설치 (`pip install anthropic`)"
    key = (secrets().get("anthropic") or {}).get("api_key")
    if not key or key == "???":
        return False, "secrets.yaml 의 anthropic.api_key 미설정"
    if not _load_rfp_skill():
        return False, f"/rfp 스킬 파일 없음 — 다음 경로 중 하나 필요: {[str(p) for p in _RFP_SKILL_PATHS]}"
    return True, "ok"


def _resolve_effort(effort: str, model: str) -> str:
    """xhigh 는 Opus 4.7 전용. 다른 모델이면 high 로 폴백."""
    if effort == "xhigh" and "opus-4-7" not in model:
        log.info("effort=xhigh 는 Opus 4.7 전용 — %s 에서는 'high' 로 폴백", model)
        return "high"
    # sonnet은 max 불가
    if effort == "max" and "opus" not in model:
        log.info("effort=max 는 Opus 전용 — %s 에서는 'high' 로 폴백", model)
        return "high"
    return effort


def generate_llm_draft(
    *,
    title: str,
    company_context: str,
    announcement_excerpt: str,
    form_excerpt: str | None = None,
    model: str | None = None,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    effort: str | None = None,
) -> str:
    """`/rfp` 스킬 룰로 1차 초안 작성. Opus 4.7 + adaptive thinking + xhigh 기본.

    Returns:
        Markdown 문자열 (브레인스토밍 카드 + 1번 선택 + 표준 6목차 뼈대 + footer)
    """
    from anthropic import Anthropic

    sec = secrets().get("anthropic") or {}
    api_key = sec.get("api_key")
    model = model or sec.get("model", DEFAULT_MODEL)
    effort = effort or sec.get("effort", DEFAULT_EFFORT)
    effort = _resolve_effort(effort, model)

    skill_text = _load_rfp_skill() or ""
    if not skill_text:
        raise RuntimeError("/rfp 스킬 파일을 찾을 수 없음")

    client = Anthropic(api_key=api_key)

    # 사용자 메시지 구성
    user_parts = [
        "# 공고 정보\n",
        f"## 공고명\n{title}\n",
        f"## 공고 본문 발췌\n```\n{announcement_excerpt[:8000]}\n```\n",
    ]
    if form_excerpt:
        user_parts.append(f"## 첨부 양식 발췌\n```\n{form_excerpt[:4000]}\n```\n")
    user_parts.append(f"\n# 회사 컨텍스트\n{company_context}\n")
    user_parts.append(
        "\n---\n\n"
        "# 작업 요청\n\n"
        "위 정보를 바탕으로 `/rfp` 스킬의 작성 룰(공문체+개조식, "
        "출처 없는 수치 ??? 표기, hallucination 방지)을 엄격히 지키면서 "
        "**한 번의 응답에 다음을 순서대로 모두 출력**해줘:\n\n"
        "## Part 1: 브레인스토밍 (스킬 Step 0)\n"
        "차별화 방향 3~5개 아이디어 카드 — 스킬에 정의된 양식 그대로 (한줄 헤드라인, "
        "핵심 포지셔닝, 기술 접근, 타겟 수요처, 컨소시엄 후보, 예상 KPI 축, 강점, 약점/리스크, 사업화 경로) "
        "+ 비교 한눈에 보기 표.\n\n"
        "## Part 2: 자동 선택\n"
        "위 아이디어 중 **회사 OFFen 라인업(ASM/AI Hacker/RED)과 가장 정합도 높은 1개**를 "
        "골라 선택 이유를 3~4문장으로 설명.\n\n"
        "## Part 3: 뼈대 작성\n"
        "선택한 방향으로 스킬의 표준 6목차(1.필요성 → 6.표준화)에 맞춰 뼈대 작성. "
        "확정 정보는 채우고, 자료조사 필요 항목은 `???(조사 필요)` 명시. "
        "회사 컨텍스트의 정량 데이터(특허 38건, 표준 28건, 23.8만 건 DB, KISA 2026 선정 등)는 "
        "그대로 활용. 글로벌 인용(AISLE/Strobes/Aikido/ArmorCode)도 적절히 배치.\n"
    )
    user_msg = "".join(user_parts)

    # Streaming + adaptive thinking + xhigh effort
    # max_tokens=32000 이라 streaming 필수 (SDK가 큰 max_tokens 비스트리밍 호출 차단)
    with client.messages.stream(
        model=model,
        max_tokens=max_tokens,
        thinking={"type": "adaptive"},
        output_config={"effort": effort},
        system=[
            {
                "type": "text",
                "text": skill_text,
                "cache_control": {"type": "ephemeral"},  # 5분 캐시
            }
        ],
        messages=[{"role": "user", "content": user_msg}],
    ) as stream:
        response = stream.get_final_message()

    # 텍스트 블록만 추출 (thinking 블록은 display=omitted 기본이라 비어있음)
    out_parts = []
    for block in response.content:
        if block.type == "text":
            out_parts.append(block.text)
    text = "\n".join(out_parts)

    # 메타데이터 푸터 — 모델·thinking 설정·토큰·실제 비용
    usage = response.usage
    cost = _calc_cost(response.model, usage)
    krw = int(cost * 1400)
    cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
    cache_write = getattr(usage, "cache_creation_input_tokens", 0) or 0
    footer = (
        f"\n\n---\n"
        f"*🤖 LLM 자동 생성 — 모델: `{response.model}` · "
        f"adaptive thinking, effort=`{effort}` · "
        f"입력 {usage.input_tokens:,} (캐시 read {cache_read:,}, write {cache_write:,}) / "
        f"출력 {usage.output_tokens:,} 토큰 · "
        f"**실제 비용: ${cost:.4f} (약 {krw:,}원)***"
    )
    return text + footer


def _calc_cost(model: str, usage) -> float:
    """response.usage 를 받아 실제 비용($) 계산."""
    p = None
    for key, val in _PRICING.items():
        if key in model:
            p = val
            break
    if p is None:
        p = _PRICING["claude-opus-4-7"]

    cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
    cache_write = getattr(usage, "cache_creation_input_tokens", 0) or 0
    # input_tokens 는 cache 미반영분 (Anthropic SDK 0.40+ 기준)
    fresh_input = max(0, usage.input_tokens - cache_read - cache_write)

    cost = (
        fresh_input * p["input"] / 1_000_000
        + cache_read * p["cache_read"] / 1_000_000
        + cache_write * p["cache_write"] / 1_000_000
        + usage.output_tokens * p["output"] / 1_000_000
    )
    return cost


def estimate_cost_range(has_form: bool = False) -> tuple[float, float]:
    """호출 전 예상 비용 범위 ($) — Opus 4.7 + adaptive thinking + xhigh effort 기준.

    실제 호출 후 footer 의 실제 비용이 정확한 값.
    """
    sys_tokens = 3500                                   # rfp.md 스킬
    user_tokens = 8000 + 1500 + (4000 if has_form else 0) + 1500  # 공고+회사+양식+지시
    # adaptive thinking + xhigh: 사고 5K~15K + 출력 3K~6K
    out_min = 8000
    out_max = 20000

    p = _PRICING[DEFAULT_MODEL]

    # 첫 호출 (system 캐시 write)
    base_input = (
        sys_tokens * p["cache_write"] / 1_000_000
        + user_tokens * p["input"] / 1_000_000
    )
    cost_min = base_input + out_min * p["output"] / 1_000_000
    cost_max = base_input + out_max * p["output"] / 1_000_000
    return cost_min, cost_max
