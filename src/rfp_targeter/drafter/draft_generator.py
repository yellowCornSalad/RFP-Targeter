"""고득점 공고의 RFP 초안 생성기.

/rfp 슬래시 커맨드의 표준 목차를 그대로 가져와서, 공고에서 추출 가능한
정보는 채우고 나머지는 ???(조사 필요) 로 명시.

실제 작성·자료조사는 Claude Code에서 사용자가 `/rfp drafts/{id}.md` 호출해서
이어가는 것을 가정.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from rfp_targeter.config import DRAFTS_DIR, profile
from rfp_targeter.db.models import Announcement, Score, get_conn


SKELETON_TEMPLATE = """# {title}

> **자동 생성 초안 (draft)** — `/rfp` 슬래시 커맨드로 이어 작성 권장
> 생성일: {generated_at}
> 공고 URL: {url}

## 0. 공고 메타데이터

| 항목 | 값 |
|------|----|
| 발주기관 | {agency} |
| 공고 ID | `{external_id}` |
| 등록일 | {posted_at} |
| 마감일 | {deadline_at} |
| 사업비 | {budget} |
| 사업기간 | {duration} |
| 보안 키워드 매칭 | {matched_kw} |

## 점수 (자동 산정)

| 지표 | 점수 |
|------|------|
| 키워드 적합도 | {s_kw}/100 |
| 예산 적합도 | {s_bg}/100 |
| 컨소시엄 부담 | {s_cs}/100 |
| 경쟁 상황 | {s_cp}/100 |
| 기술 TRL 적합 | {s_tr}/100 |
| **종합** | **{s_total}/100** |
| 테마 적합도 | {s_theme}/100 |

### 점수 산정 근거
```json
{rationale}
```

---

## 공고 요약
{summary}

---

## 1. 연구개발과제의 필요성
- 1-1. 연구개발과제의 개요(배경): ???(작성 필요)
- 1-2. 국내외 현황: ???(자료조사 필요)

## 2. 연구개발과제의 목표 및 내용
- 2-1. 최종 목표 + KPI: ???
- 2-2. 연차별 연구 내용 및 결과물: ???

## 3. 추진전략·방법 및 추진체계
- 컨소시엄 구성 후보(회사 프로필 기반): {consortium_candidates}
- 회사 보유 기술 매칭: {tech_match}

## 4. 활용방안 및 기대효과
- (1) 기술적 측면: ???
- (2) 경제적·산업적 측면: ???
- (3) 사회적 측면: ???

## 5. 사업화 전략
- 1차 수요처: ???
- 2차 수요처: ???
- 수익 모델 (라이선스/SaaS/컨설팅/매니지드): ???

## 6. 표준화 전략
- ???

---

## 다음 단계
1. Claude Code에서 `/rfp {draft_path}` 실행 → 브레인스토밍 단계 진입
2. ???로 표시된 항목 자료조사 (`출처` 명시 필수)
3. 양식 파일과 매칭: `templates/{agency_dir}/` 확인
"""


def _format(a: Announcement, s: Score | None, profile_data: dict) -> str:
    techs = profile_data.get("technologies") or []
    blob = ((a.title or "") + " " + (a.summary or "") + " " + (a.body or "")).lower()
    matched_techs = [
        t["name"] for t in techs
        if any(kw.lower() in blob for kw in t.get("keywords", []))
    ]
    cons = profile_data.get("consortium") or {}
    raw_partners = cons.get("existing_partners") or []
    # existing_partners 는 dict 또는 string 형태 모두 지원
    partners = [
        (p.get("name") + (f" ({p.get('evidence')})" if p.get("evidence") else ""))
        if isinstance(p, dict) else str(p)
        for p in raw_partners
    ]

    return SKELETON_TEMPLATE.format(
        title=a.title,
        generated_at=datetime.now().isoformat(timespec="seconds"),
        url=a.url,
        agency=a.agency or "???",
        external_id=a.external_id,
        posted_at=a.posted_at or "???",
        deadline_at=a.deadline_at or "???",
        budget=f"{a.budget_mw}백만원" if a.budget_mw else "???",
        duration=f"{a.duration_months}개월" if a.duration_months else "???",
        matched_kw=", ".join(a.matched_keywords) if a.matched_keywords else "없음",
        s_kw=s.keyword_score if s else "?",
        s_bg=s.budget_score if s else "?",
        s_cs=s.consortium_score if s else "?",
        s_cp=s.competitor_score if s else "?",
        s_tr=s.trl_score if s else "?",
        s_total=s.total_score if s else "?",
        s_theme=s.theme_fit if s else "?",
        rationale=json.dumps(s.rationale, ensure_ascii=False, indent=2) if s else "{}",
        summary=a.summary or "(요약 없음)",
        consortium_candidates=", ".join(partners) if partners else "???",
        tech_match=", ".join(matched_techs) if matched_techs else "(매칭된 보유 기술 없음 — 외부 협력 검토)",
        agency_dir=(a.agency or "unknown").replace(" ", "_"),
        draft_path=f"drafts/{a.id.replace(':', '_')}.md",
    )


def generate_draft(a: Announcement, s: Score | None = None) -> Path:
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
    content = _format(a, s, profile())
    path = DRAFTS_DIR / f"{a.id.replace(':', '_')}.md"
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
