"""LLM 맥락 판단 — 공고 본문을 '읽고' (1) 실제 TRL 단계 (2) 회사 도메인 적합성 평가.

배경 (2026-06-01 사용자 요청):
- 기존 TRL/키워드 점수는 단어 '존재'만 확인 (예: '사업화'가 자격요건 문장에 4번
  나왔다는 이유로 TRL 95). 그 단어가 그 맥락에서 정말 의미 있는지는 못 봄.
- LLM(claude-haiku-4-5)이 본문 맥락을 읽고 판단 → 단순 매칭 한계 보완.

원칙:
- 본문 근거로만. 추정·외부지식·hallucination 금지. 근거 없으면 보수적(null/낮음).
- claude-haiku-4-5 (저렴·빠름, 1건 ~$0.002). JSON 반환. 결과는 DB 캐시(1회 생성).

사용:
    from rfp_targeter.llm_assess import assess_announcement
    res = assess_announcement(title, body)  # 실패 시 None
    # {"trl": 8|None, "trl_reason": "...", "relevance": "high|medium|low|none",
    #  "relevance_reason": "..."}
"""
from __future__ import annotations

import json
import logging

from rfp_targeter.config import profile, secrets

log = logging.getLogger(__name__)

_MODEL = "claude-haiku-4-5"


def _company_context() -> str:
    """도메인 적합성 판단 기준이 되는 회사 정체성 (profile.yaml 기반)."""
    p = profile() or {}
    c = p.get("company") or {}
    name = c.get("name") or "엔키화이트햇"
    return (
        f"회사명: {name}\n"
        "업종: 사이버보안 전문 기업 (공격형 보안 / 모의해킹·침투시험 / AI 기반 보안 자동화)\n"
        "주력 자산: OFFen 라인업(AI DAST 웹취약점 자동진단, PTaaS 침투테스트, "
        "ASM 공격표면관리), 보안 컨설팅·취약점 진단·보안 R&D, 위협 인텔리전스\n"
        "보유 TRL: 8~9 (사업화·상용화 단계 보안 제품/서비스)\n"
        "★ 회사가 '할 수 없는/무관한' 영역: 제조업·하드웨어 양산, 물품/장비 수출, "
        "스마트공장 구축, 일반 시설/건설, 농수산·바이오 실험 등 — 이런 사업은 적합성 낮음(low/none)"
    )


_SYSTEM = """당신은 정부 R&D/사업 공고를 '특정 회사' 관점에서 평가하는 분석가입니다.
반드시 공고 본문에 근거해서만 판단하세요. 추정·외부지식·할루시네이션 금지. 근거가 약하면 보수적으로.

두 가지를 평가해 JSON 으로만 답합니다:

1) trl (이 공고가 '대상으로 하는 기술의 성숙도 단계', TRL 1~9):
   - 단어가 한 번 등장했다고 그 단계가 아닙니다. 공고가 실제로 지원하는 단계를 보세요.
     (기초연구=2~3, 응용/원천=4~5, 시제품/파일럿=6, 실증=7, 사업화=8, 상용화/확산=9)
   - 예: '사업화 권한을 보유한 기업'처럼 자격요건 안의 단어는 단계 근거가 아님.
   - 본문에 단계를 가늠할 실제 근거가 없으면 null.

2) relevance (이 공고를 위 회사가 실제로 신청·수행할 수 있는 사업인지 = 도메인 적합성):
   - high: 보안·취약점·침투·모의해킹·정보보호·AI보안·관제 등 본업 직결
   - medium: 일반 AI/SW/데이터/클라우드 R&D (보안과 인접, 컨소시엄 참여 여지)
   - low: 본업과 거리가 먼 분야지만 일부 IT 요소 존재
   - none: 제조·수출·하드웨어·스마트공장·시설·농수산 등 회사가 수행 불가

출력은 아래 JSON 한 줄만. 다른 텍스트·코드펜스·설명 금지:
{"trl": <1~9 정수 또는 null>, "trl_reason": "<한 줄 근거, 본문 인용 위주>", "relevance": "high|medium|low|none", "relevance_reason": "<한 줄 근거>"}"""


def assess_announcement(title: str, body: str, max_chars: int = 4000) -> dict | None:
    """본문 맥락 기반 TRL 단계 + 도메인 적합성 판단. 실패 시 None."""
    if not body or len(body) < 100:
        return None
    try:
        import anthropic
    except ImportError:
        log.debug("anthropic SDK 미설치 — assess 건너뜀")
        return None

    sec = secrets() or {}
    api_key = (sec.get("anthropic") or {}).get("api_key")
    if not api_key or api_key in ("???", "PASTE_YOUR_KEY"):
        log.debug("anthropic api_key 미설정 — assess 건너뜀")
        return None

    user = (
        f"[평가 대상 회사]\n{_company_context()}\n\n"
        f"[공고 제목]\n{title}\n\n"
        f"[공고 본문]\n{body[:max_chars]}\n\n"
        "위 회사 관점에서 trl 과 relevance 를 평가해 JSON 으로만 답하세요."
    )

    try:
        client = anthropic.Anthropic(api_key=api_key)
        msg = client.messages.create(
            model=_MODEL,
            max_tokens=700,  # [2026-06-01] 300→700. 한국어 근거 2개(trl+relevance, 각 ~200자)면
                             # 300토큰 초과로 JSON 이 잘려 파싱 실패→None (대형 공고 40% 실패 원인).
            system=_SYSTEM,
            messages=[{"role": "user", "content": user}],
        )
        text = "".join(b.text for b in msg.content if hasattr(b, "text")).strip()
        # 코드펜스/머리말 제거 후 JSON 본체만 추출
        text = text.strip("`").strip()
        if text[:4].lower() == "json":
            text = text[4:].strip()
        i, j = text.find("{"), text.rfind("}")
        if i < 0 or j < 0:
            log.debug("assess: JSON 없음 — %r", text[:120])
            return None
        data = json.loads(text[i:j + 1])

        trl = data.get("trl")
        if not (isinstance(trl, int) and 1 <= trl <= 9):
            trl = None
        rel = data.get("relevance")
        if rel not in ("high", "medium", "low", "none"):
            rel = None
        return {
            "trl": trl,
            "trl_reason": str(data.get("trl_reason") or "")[:200],
            "relevance": rel,
            "relevance_reason": str(data.get("relevance_reason") or "")[:200],
        }
    except Exception as e:
        log.debug("assess fail: %s", e)
        return None
