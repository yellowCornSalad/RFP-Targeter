"""고득점 공고의 RFP 초안 생성기 — 풀 컨텍스트 버전.

`/rfp drafts/{id}.md` 한 줄로 즉시 브레인스토밍 단계 진입 가능하도록
회사 정보·5축 분해·매칭 키워드 분류·양식 파일 매칭·첨부 본문 발췌까지 자동 포함.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from rfp_targeter.attachments import classify, group_by_category, label
from rfp_targeter.config import DRAFTS_DIR, TEMPLATES_DIR, profile
from rfp_targeter.db.models import Announcement, Score, get_conn
from rfp_targeter.drafter import llm_writer


# ---------------------- 보조 함수 ----------------------


def _norm(s: str) -> str:
    return (s or "").replace(" ", "").lower()


def _slug(title: str, max_len: int = 50) -> str:
    """과제명을 파일명 안전한 slug로. 한글·영문·숫자 유지, 공백→하이픈, 특수문자 제거."""
    if not title:
        return "untitled"
    # 대괄호 [], 괄호 () 안 내용은 그대로 두되 괄호만 제거
    s = re.sub(r"[\[\]()【】〔〕]", " ", title)
    # 파일명 금지 문자 제거 (Windows: < > : " / \ | ? *)
    s = re.sub(r'[<>:"/\\|?*\n\r\t]', "", s)
    # 일부 마침표·따옴표·쉼표 등 정리
    s = re.sub(r"[‧·`'’“”]", "-", s)
    s = re.sub(r"[,。·]", " ", s)
    # 공백 다중 → 하이픈
    s = re.sub(r"\s+", "-", s.strip())
    # 하이픈 다중 정리
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return s[:max_len] or "untitled"


def _draft_filename(a: Announcement) -> str:
    """drafts 파일명 — source + 과제명 slug + external_id."""
    safe_id = a.external_id.replace(":", "_").replace("/", "_").replace("\\", "_")
    slug = _slug(a.title or "")
    return f"{a.source}_{slug}_{safe_id}.md"


def _match_templates(a: Announcement) -> list[Path]:
    """templates/{source}/ + templates/{agency_keyword}/ 둘 다 검색."""
    if not TEMPLATES_DIR.exists():
        return []

    candidate_dirs: list[Path] = []
    # 1) source 기반 (예: templates/IITP/, templates/KISA/)
    src_alias = {
        "iitp": "IITP",
        "kisa": "KISA",
        "mss": "MSS",
        "ntis": "NTIS",
        "krit": "KRIT",
        "bizinfo": "bizinfo",
    }.get(a.source, a.source.upper())
    candidate_dirs.append(TEMPLATES_DIR / src_alias)
    candidate_dirs.append(TEMPLATES_DIR / a.source)

    # 2) agency 기반 (예: 정보보호기획과 → templates/정보보호기획과/)
    if a.agency:
        candidate_dirs.append(TEMPLATES_DIR / a.agency.strip())
        # 첫 단어만
        first = a.agency.strip().split()[0]
        candidate_dirs.append(TEMPLATES_DIR / first)

    found: list[Path] = []
    seen_paths: set[Path] = set()
    for d in candidate_dirs:
        if not d.exists() or not d.is_dir():
            continue
        for ext in (".hwp", ".hwpx", ".pdf", ".docx", ".odt", ".xlsx", ".pptx"):
            for f in d.rglob(f"*{ext}"):
                if f not in seen_paths:
                    seen_paths.add(f)
                    found.append(f)
    return found


def _classify_keywords(matched: list[str]) -> tuple[list[str], list[str], list[str]]:
    """매칭 키워드를 부서 / 핵심(profile.core_keywords) / 보안필터 일반 으로 분류."""
    p = profile()
    core_set = {_norm(k) for k in (p.get("core_keywords") or [])}
    pos_set = {_norm(k) for k in (p.get("positioning_keywords") or [])}

    depts = []
    cores = []
    others = []
    for k in matched:
        if not isinstance(k, str):
            continue
        if k.startswith("[부서]"):
            depts.append(k.replace("[부서] ", ""))
        elif _norm(k) in core_set or _norm(k) in pos_set:
            cores.append(k)
        else:
            others.append(k)
    return depts, cores, others


def _score_breakdown(s: Score | None) -> str:
    if s is None:
        return "(점수 없음)"
    weights = {"키워드": 0.35, "예산": 0.10, "컨소시엄": 0.20, "경쟁": 0.20, "TRL": 0.15}
    rows = []
    rows.append("| 축 | 점수 | 가중치 | 가중점 |")
    rows.append("|----|------|--------|--------|")
    pairs = [
        ("키워드", s.keyword_score, "kw"),
        ("예산", s.budget_score, "bg"),
        ("컨소시엄", s.consortium_score, "cs"),
        ("경쟁", s.competitor_score, "cp"),
        ("TRL", s.trl_score, "tr"),
    ]
    weighted_total = 0.0
    for name, val, _ in pairs:
        w = weights[name]
        wpt = val * w
        weighted_total += wpt
        rows.append(f"| {name} | **{val:.1f}** | {w:.2f} | {wpt:.1f} |")
    bonus = (s.total_score or 0) - weighted_total
    bonus_str = f"+{bonus:.1f}" if bonus > 0 else f"{bonus:.1f}" if bonus < 0 else "0"
    rows.append(f"| **가중합** | | | **{weighted_total:.1f}** |")
    rows.append(f"| **테마 보너스** (theme_fit {s.theme_fit:.0f}) | | | **{bonus_str}** |")
    rows.append(f"| **종합** | | | **{s.total_score:.1f}/100** |")
    return "\n".join(rows)


def _rationale_md(s: Score | None) -> str:
    if s is None or not s.rationale:
        return "(산정 근거 없음)"
    out = []
    label_map = {
        "keyword": "🔑 키워드", "budget": "💰 예산", "consortium": "🤝 컨소시엄",
        "competitor": "⚔️ 경쟁", "trl": "🧪 TRL", "theme_fit": "🎯 테마 적합",
    }
    for k, label in label_map.items():
        lines = s.rationale.get(k) or []
        if not lines:
            continue
        out.append(f"**{label}**")
        for line in lines:
            out.append(f"- {line}")
        out.append("")
    return "\n".join(out)


def _body_excerpt(a: Announcement, limit: int = 1500) -> str:
    if not a.body:
        return "(본문 없음)"
    body = a.body.strip()
    if "[첨부 본문]" in body:
        body = body.split("[첨부 본문]", 1)[1].strip()
    body = body.replace("\n", " ").strip()
    return body[:limit] + ("..." if len(body) > limit else "")


def _company_context_section(profile_data: dict, matched_tech_names: list[str]) -> str:
    """회사 정보 섹션 — 제안서 작성 시 활용 가능한 풀 컨텍스트."""
    company = profile_data.get("company", {})
    techs = profile_data.get("technologies", [])
    ip = (profile_data.get("track_record") or {}).get("ip_assets", {})
    stds = (profile_data.get("track_record") or {}).get("standards", {})
    awards = (profile_data.get("track_record") or {}).get("past_awards", [])
    data = (profile_data.get("track_record") or {}).get("data_assets", {})
    cons = profile_data.get("consortium", {})
    partners = cons.get("existing_partners") or []
    positioning = profile_data.get("positioning_keywords") or []
    target = profile_data.get("target_markets") or {}
    policy = profile_data.get("policy_alignment") or []

    lines = ["## 🏢 회사 컨텍스트 (작성 시 활용)\n"]

    # 포지셔닝
    pos_str = company.get("positioning") or ""
    if pos_str:
        lines.append(f"> **{pos_str}**\n")

    # 제품 라인업
    if techs:
        lines.append("### 제품·기술 라인업")
        for t in techs:
            highlight = " ⭐ **공고 본문과 매칭됨**" if t.get("name") in matched_tech_names else ""
            lines.append(f"- **{t.get('name', '?')}** (TRL {t.get('trl', '?')}){highlight}")
        lines.append("")

    # 5년 누적 자산
    lines.append("### 5년간 누적 자산 (재현 불가)")
    if data:
        lines.append(
            f"- **{data.get('hacker_knowledge_db_count', 0):,}건 해커 지식 DB** "
            f"({data.get('db_accumulation_years','?')}년 축적, 자체 생성 {data.get('self_generated_pct','?')}%)"
        )
    if ip:
        ip_total = ip.get("patents_total") or (
            (ip.get("patents_registered_domestic") or 0)
            + (ip.get("patents_pending_domestic") or 0)
            + (ip.get("patents_filed_overseas") or 0)
        )
        lines.append(
            f"- **특허 {ip_total}건** "
            f"(국내 등록 {ip.get('patents_registered_domestic','?')} + "
            f"국내 출원 {ip.get('patents_pending_domestic','?')} + "
            f"국외 출원 {ip.get('patents_filed_overseas','?')})"
        )
        if ip.get("tech_escrow_years"):
            lines.append(f"- 핵심 기술자료 **{ip['tech_escrow_years']}년 임치** (IP 자산화)")
    if stds:
        lines.append(
            f"- **표준화 활동 {(stds.get('domestic_count') or 0) + (stds.get('international_count') or 0)}건** "
            f"(국내 {stds.get('domestic_count','?')} · 국외 {stds.get('international_count','?')})"
        )
    lines.append("")

    # 정부 사업 레퍼런스
    if awards:
        lines.append("### 정부 사업 레퍼런스")
        for aw in awards:
            lines.append(
                f"- **{aw.get('agency','?')} {aw.get('program','')}** ({aw.get('year','?')}): "
                f"{aw.get('title','?')}"
            )
        lines.append("")

    # 컨소시엄 검증 파트너
    if partners and partners != ["???"]:
        lines.append("### 컨소시엄 파트너 (검증된 실적)")
        for p in partners:
            if isinstance(p, dict):
                ev = f" — {p.get('evidence')}" if p.get("evidence") else ""
                lines.append(f"- **{p.get('name','?')}**{ev}")
            else:
                lines.append(f"- {p}")
        lines.append("")

    # 타깃 시장
    if target:
        primary = target.get("primary_domestic") or []
        intl = target.get("international") or []
        if primary or intl:
            lines.append("### 타깃 시장")
            if primary:
                lines.append(f"- 1차 국내: {', '.join(primary)}")
            if intl:
                lines.append(f"- 해외: {', '.join(intl)} (외산 AI 전송 불가 시장)")
            lines.append("")

    # 글로벌 정책 정합
    if policy:
        lines.append("### 글로벌 정책·규제 정합")
        for pol in policy:
            lines.append(f"- {pol}")
        lines.append("")

    # 차별화 메시지
    if positioning:
        lines.append("### 차별화 핵심 메시지 (헤드라인 후보)")
        for msg in positioning[:6]:
            lines.append(f"- \"{msg}\"")
        lines.append("")

    return "\n".join(lines)


def _group_same_file(atts: list[dict]) -> list[dict]:
    """같은 파일의 다른 확장자(.hwp/.hwpx/.odt 등)를 1개로 묶음.

    정부 API는 한컴 파일(.hwp/.hwpx) + ODF 변환본(.odt)을 모두 반환하지만
    실제 페이지엔 .hwp/.hwpx만 노출됨. 우리도 그룹화해서 표시 깔끔하게.

    그룹 내 대표 선택 우선순위: .hwpx > .pdf > .hwp > .docx > .odt > 기타
    """
    def _ext(name: str) -> str:
        m = re.search(r"\.([^.\s)]+)$", name or "")
        return m.group(1).lower() if m else ""

    def _basename(name: str) -> str:
        return re.sub(r"\.[^.\s)]+$", "", name or "").strip().lower()

    def _ext_pri(ext: str) -> int:
        order = {"hwpx": 0, "pdf": 1, "hwp": 2, "docx": 3, "odt": 4, "zip": 5}
        return order.get(ext, 9)

    groups: dict[str, list[dict]] = {}
    for att in atts:
        key = _basename(att.get("name", ""))
        groups.setdefault(key, []).append(att)

    merged = []
    for key, items in groups.items():
        items.sort(key=lambda x: _ext_pri(_ext(x.get("name", ""))))
        primary = items[0]
        alt = [_ext(x.get("name", "")) for x in items[1:] if _ext(x.get("name", ""))]
        primary = dict(primary)  # copy
        primary["_alt_formats"] = alt
        primary["_alt_items"] = items[1:]  # 다른 형식 URL 보존
        merged.append(primary)
    return merged


def _attachments_section(a: Announcement, templates: list[Path]) -> str:
    """공고 첨부를 카테고리별로 분류 + 동일 파일은 형식별로 그룹화."""
    atts = a.attachments or []
    if not atts and not templates:
        return (
            "## 🗂️ 양식·첨부 파일\n\n"
            "> 첨부 파일 메타 없음.\n"
        )

    for att in atts:
        if not att.get("category"):
            att["category"] = classify(att.get("name", ""))

    # 같은 파일명(확장자만 다름)을 그룹화
    merged = _group_same_file(atts)
    grouped = group_by_category(merged)

    lines = ["## 🗂️ 공고 첨부 파일\n"]

    order = ["form", "notice", "eval", "reference", "other"]
    for cat in order:
        items = grouped.get(cat) or []
        if not items:
            continue
        cat_label = label(cat)
        if cat == "form":
            lines.append(f"### {cat_label} ⭐ **이 양식에 맞춰 작성**")
        else:
            lines.append(f"### {cat_label}")
        for att in items:
            name = att.get("name") or "(이름 없음)"
            url = att.get("url") or ""
            local = att.get("local_path")
            alt_formats = att.get("_alt_formats") or []
            alt_items = att.get("_alt_items") or []
            # 다른 형식 다운로드 링크 모음
            alt_links = ""
            if alt_items:
                parts = []
                for ai in alt_items:
                    ext = re.search(r"\.([^.\s)]+)$", ai.get("name", "")).group(1).lower() if re.search(r"\.([^.\s)]+)$", ai.get("name", "")) else ""
                    aurl = ai.get("url") or ""
                    if aurl and ext:
                        parts.append(f"[.{ext}]({aurl})")
                if parts:
                    alt_links = " · 다른 형식: " + " ".join(parts)
            local_note = f" · 로컬: `{local}`" if local else ""
            if url:
                lines.append(f"- [{name}]({url}){alt_links}{local_note}")
            else:
                lines.append(f"- {name}{alt_links}{local_note}")
        lines.append("")

    # 회사 공통 양식 (templates/ 폴더)
    if templates:
        lines.append("### 📁 회사 공통 양식 (templates/ 폴더)")
        for p in templates:
            try:
                rel = p.relative_to(TEMPLATES_DIR.parent)
            except ValueError:
                rel = p
            size_kb = p.stat().st_size // 1024
            lines.append(f"- `{rel}` ({size_kb} KB)")
        lines.append("")

    return "\n".join(lines)


# ---------------------- 메인 ----------------------


def _format(a: Announcement, s: Score | None, profile_data: dict) -> str:
    techs = profile_data.get("technologies") or []
    blob = ((a.title or "") + " " + (a.summary or "") + " " + (a.body or "")).lower()
    matched_tech_names = [
        t["name"] for t in techs
        if any(_norm(kw) in _norm(blob) for kw in (t.get("keywords") or []))
    ]

    depts, cores, others = _classify_keywords(a.matched_keywords or [])
    templates = _match_templates(a)
    draft_path = f"drafts/{_draft_filename(a)}"

    sections = []

    # 헤더
    sections.append(f"# {a.title}\n")
    sections.append(
        f"> 🤖 **자동 생성 초안** · 생성일 {datetime.now().strftime('%Y-%m-%d %H:%M')} · "
        f"[공고 원문 ↗]({a.url})\n"
    )

    # 0. 공고 메타
    sections.append("## 📋 공고 메타데이터\n")
    sections.append("| 항목 | 값 |\n|------|----|")
    sections.append(f"| 발주기관 | {a.agency or '???'} |")
    sections.append(f"| 공고 ID | `{a.external_id}` |")
    sections.append(f"| 등록일 | {a.posted_at or '???'} |")
    sections.append(f"| 마감일 | {a.deadline_at or '???'} |")
    sections.append(f"| 사업비 | {f'{a.budget_mw}백만원' if a.budget_mw else '???'} |")
    sections.append(f"| 사업기간 | {f'{a.duration_months}개월' if a.duration_months else '???'} |")
    sections.append("")

    # 1. 매칭 결과 (왜 이 공고를 보여주나)
    sections.append("## 🎯 매칭 결과 — 왜 이 공고가 선정되었나\n")
    if depts:
        sections.append(f"**🏢 발주 부서 매칭** (회사 본업 핵심 부서): {' · '.join(depts)}")
    if cores:
        sections.append(f"**🔑 회사 핵심 키워드 매칭**: {' · '.join(cores)}")
    if others:
        shown = others[:12]
        more = len(others) - 12
        tail = f" 외 {more}개" if more > 0 else ""
        sections.append(f"**📌 보안 사전 매칭**: {' · '.join(shown)}{tail}")
    if matched_tech_names:
        sections.append(f"**⭐ 회사 보유 기술 직접 매칭**: {' · '.join(matched_tech_names)}")
    sections.append("")

    # 2. 점수 분해
    sections.append("## 📐 점수 분해\n")
    sections.append(_score_breakdown(s))
    sections.append("")
    sections.append("<details><summary>📊 산정 근거 상세</summary>\n")
    sections.append(_rationale_md(s))
    sections.append("</details>\n")

    # 3. 첨부 분류 (공고 첨부에서 양식/공고문/평가표/참고 자동 분류)
    sections.append(_attachments_section(a, templates))

    # 4. 공고 본문 발췌
    sections.append("## 📄 공고 본문 발췌 (자동 추출)\n")
    sections.append("```")
    sections.append(_body_excerpt(a))
    sections.append("```\n")

    # 5. 회사 컨텍스트
    sections.append(_company_context_section(profile_data, matched_tech_names))

    # 6. 표준 6 목차 (가이드형) — f-string 사용 (.format() 쓰면 다른 {} 충돌)
    src_dir = a.source.upper() if a.source else "기관"
    guide = f"""---

## ✍️ 제안서 표준 목차 (작성 가이드)

### 1. 연구개발과제의 필요성
- **1-1. 배경**: 정책 변화 → 기술 한계 → 시장 수요 → 본 과제 필요성
  - ???(작성 필요) — 회사 §2.1 "AI 활용 공격 일반화" 인용 가능
- **1-2. 국내외 현황**:
  - 국내: ???(자료조사)
  - 글로벌: "The moat is the system, not the model" — AISLE/Strobes/Aikido/ArmorCode 인용 가능 (회사 §5.2)
  - 정책: EU AI Act / 미국 CSRB / KISA AI 보안 안내서 / 일본 ISMAP / 사우디 PDPL (회사 §9.3)

### 2. 연구개발과제의 목표 및 내용
- **2-1. 최종 목표 + KPI**:
  - ??? — 회사 정량 평가 지표 활용 (공격 가능 자산 비율, 핵심 자산 침투 차단율, 평균 대응 시간)
- **2-2. 연차별 연구 내용**:
  - 1년차: ??? / 2년차: ??? / 3년차: ???

### 3. 추진전략·방법 및 추진체계
- **주관기관**: 엔키화이트햇 (단독 수행 가능 — OFFen 통합 플랫폼 보유)
- **공동기관 후보**: (위 "컨소시엄 파트너" 활용)
- **회사 보유 기술 매핑**: (위 "⭐ 회사 보유 기술 직접 매칭" 참고)
- **추진 일정**: ???

### 4. 활용방안 및 기대효과
- **(1) 기술적 측면**: ??? — 회사 §7 정량 평가 데이터 활용
- **(2) 경제적·산업적 측면**: ??? — 사업화 모델 4종(라이선스/SaaS/On-Premise/매니지드)
- **(3) 사회적 측면**: ???

### 5. 사업화 전략
- **1차 수요처**: (회사 타깃 시장 활용)
- **2차 수요처**: ???
- **수익 모델**: 라이선스 / SaaS / 컨설팅 / 매니지드 서비스
- **정부 사업 레퍼런스**: KISA 2026 신기술 사업화 선정 (LLM 기반 자율 공격형 웹 취약점 검증)

### 6. 표준화 전략
- **참여 표준**: TTAK.OT-12.0001 (조직 보안 수준 정량 측정) / ITU-T X.1521 (CVSS) / X.1525 (CWSS) / STIX 시리즈
- **글로벌 정합**: EU AI Act / 미국 CSRB / ISO/IEC 27004
- **IP 활용**: 회사 특허 38건 + 표준화 28건 (위 회사 컨텍스트 참고)

---

## 🚀 다음 단계

1. **Claude Code에서**: `/rfp {draft_path}`
   → 위 모든 컨텍스트가 자동 반영되어 **브레인스토밍 단계(아이디어 카드 3~5개)** 진입
2. **자료조사 필요 항목**: 위 `???` 표시된 모든 항목 — `(출처: 기관명, 연도)` 명시 필수
3. **참고 문서**:
   - 회사 종합 정리: `docs/company_profile.md`
   - 점수 산정 기준: `docs/scoring_guide.md`
   - 양식 파일: `templates/{src_dir}/` (위 §🗂️ 매칭된 양식 확인)
"""
    sections.append(guide)

    return "\n".join(sections)


def generate_draft(a: Announcement, s: Score | None = None, use_llm: bool = False) -> Path:
    """가이드 초안 생성. use_llm=True이고 API 키·rfp 스킬 사용 가능 시 LLM 1차 초안까지 추가."""
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
    content = _format(a, s, profile())

    if use_llm:
        ok, reason = llm_writer.is_available()
        if ok:
            try:
                # LLM 호출 시 회사 컨텍스트는 _company_context_section 결과 재사용
                p = profile()
                techs = p.get("technologies") or []
                blob = ((a.title or "") + " " + (a.summary or "") + " " + (a.body or "")).lower()
                matched_tech_names = [
                    t["name"] for t in techs
                    if any(_norm(kw) in _norm(blob) for kw in (t.get("keywords") or []))
                ]
                company_ctx = _company_context_section(p, matched_tech_names)
                # 양식 발췌 (있으면)
                form_text = None
                for att in (a.attachments or []):
                    if att.get("category") == "form" and att.get("local_path"):
                        from rfp_targeter.attachments import extract_text
                        form_text = extract_text(Path(att["local_path"]))
                        if form_text:
                            break

                llm_body = llm_writer.generate_llm_draft(
                    title=a.title or "",
                    company_context=company_ctx,
                    announcement_excerpt=a.body or "",
                    form_excerpt=form_text,
                )
                content += "\n\n---\n\n# 🤖 AI 1차 초안 (`/rfp` 스킬 자동 적용)\n\n" + llm_body
            except Exception as e:
                content += f"\n\n---\n\n> ⚠️ LLM 호출 실패: {e}\n"
        else:
            content += f"\n\n---\n\n> ℹ️ LLM 자동 작성 스킵: {reason}\n"

    path = DRAFTS_DIR / _draft_filename(a)
    path.write_text(content, encoding="utf-8")
    return path


def generate_for_high_scoring(min_score: float = 70.0) -> list[Path]:
    """현재 DB에서 임계점 이상 공고 모두 초안 생성."""
    paths: list[Path] = []
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT a.*, s.*
            FROM announcement a
            JOIN score s ON s.announcement_id = a.id
            WHERE a.is_security = 1 AND s.total_score >= ?
              AND a.id NOT IN (SELECT announcement_id FROM draft)
            """,
            (min_score,),
        ).fetchall()
        for row in rows:
            a = Announcement(
                source=row["source"],
                external_id=row["external_id"],
                title=row["title"],
                url=row["url"],
                agency=row["agency"],
                posted_at=row["posted_at"],
                deadline_at=row["deadline_at"],
                budget_mw=row["budget_mw"],
                duration_months=row["duration_months"],
                summary=row["summary"],
                body=row["body"],
                matched_keywords=json.loads(row["matched_keywords_json"] or "[]"),
                is_security=bool(row["is_security"]),
            )
            s = Score(
                announcement_id=a.id,
                keyword_score=row["keyword_score"],
                budget_score=row["budget_score"],
                consortium_score=row["consortium_score"],
                competitor_score=row["competitor_score"],
                trl_score=row["trl_score"],
                total_score=row["total_score"],
                theme_fit=row["theme_fit"],
                rationale=json.loads(row["rationale_json"] or "{}"),
            )
            path = generate_draft(a, s)
            conn.execute(
                """
                INSERT INTO draft(announcement_id, file_path, status, generated_at)
                VALUES (?, ?, 'generated', ?)
                """,
                (a.id, str(path), datetime.now().isoformat(timespec="seconds")),
            )
            paths.append(path)
    return paths
