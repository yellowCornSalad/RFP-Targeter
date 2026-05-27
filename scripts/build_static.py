"""Supabase → 정적 사이트 빌드.

매시 cron이 실행:
  1. Supabase에서 보안 통과 announcement + score 모두 fetch
  2. site/data.json — 클라이언트 JS가 fetch해서 필터링/검색
  3. site/index.html — BMW 톤 + Vanilla JS (외부 의존 X, CDN만)
  4. site/styles.css — BMW 디자인 토큰
  5. site/app.js — 필터·검색·카드 펼침·차트

site/ 출력은 GitHub Pages가 자동 서빙.

사용:
    python scripts/build_static.py            # 전체 빌드 → site/
    python scripts/build_static.py --out dist # 다른 디렉터리
"""
from __future__ import annotations

import argparse
import html as _html
import json
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rfp_targeter.db.models import get_conn  # noqa: E402


# ─────────────────────────────────────────────────────────────
# 매칭 키워드 표시 정규화 — 카드 #키워드 칩 dedupe + 별칭 통합.
# 같은 의미의 변형 (AI/인공지능, SW/소프트웨어, PQC/양자내성암호 등) 을 1개로 합치고
# 공백만 다른 변형 (정보보호/정보 보호) 도 dedupe. 한글 우선 표시.
# ─────────────────────────────────────────────────────────────

# 영문 약어 → 한글 대표 표기. 의미 같으면 한 칩으로 묶음.
_KEYWORD_ALIASES = {
    "ai": "인공지능",
    "sw": "소프트웨어",
    "dx": "디지털전환",
    "ax": "디지털전환",
    "ict": "정보통신",
    "pqc": "양자내성암호",
    "llm": "거대언어모델",
    "cybersecurity": "사이버보안",
    "cyber security": "사이버보안",
    "infosec": "정보보호",
    "information security": "정보보호",
    "penetration test": "침투시험",
    "vulnerability": "취약점",
    "threat intelligence": "위협 인텔리전스",
    "zero trust": "제로트러스트",
}


def _normalize_keywords_display(keywords: list[str]) -> list[str]:
    """매칭 키워드 정규화 + dedupe.

    1) [부서] 접두사는 별개 — 변형 안 함, 앞에 배치
    2) _KEYWORD_ALIASES 매핑 적용 (AI → 인공지능 등)
    3) 공백 제거 + 소문자 기준 dedupe — 같은 키는 한글 우선, 짧은 표기 우선
    """
    if not keywords:
        return []
    seen: dict[str, str] = {}  # normalized_key → 최종 표시 키워드
    depts: list[str] = []

    def has_korean(s: str) -> bool:
        return any("가" <= c <= "힯" for c in s)

    for kw in keywords:
        if not isinstance(kw, str) or not kw.strip():
            continue
        if kw.startswith("[부서]"):
            depts.append(kw)
            continue
        # 별칭 매핑 (소문자 기준)
        mapped = _KEYWORD_ALIASES.get(kw.lower(), kw)
        # dedupe 키 — 공백 제거 + 소문자
        key = mapped.replace(" ", "").lower()
        if key in seen:
            existing = seen[key]
            # 한글이 있는 표기 우선
            kor_new = has_korean(mapped)
            kor_old = has_korean(existing)
            if kor_new and not kor_old:
                seen[key] = mapped
            elif kor_new == kor_old:
                # 둘 다 한글이거나 둘 다 영문 — 공백 없는 표기 우선 (정규 표기로 통일)
                if mapped.count(" ") < existing.count(" "):
                    seen[key] = mapped
        else:
            seen[key] = mapped

    return depts + list(seen.values())


# ─────────────────────────────────────────────────────────────
# 본문 가독성 처리 — Streamlit dashboard.py 의 task #71 로직 포팅.
# 정부 공문 마커 줄바꿈, 표 분해, 한글 공백 제거, 사이트 chrome 텍스트 정리.
# 결과는 마커 토큰(§§HEAD§§, §§NOTE§§)을 포함한 plain text — JS가 토큰별로 클래스 입힘.
# ─────────────────────────────────────────────────────────────

_CHROME_PATTERNS = [
    r"알림마당\s*입찰공고\s*인쇄하기\s*공유하기\s*닫기\s*트위터\s*페이스북",
    r"인쇄하기\s*공유하기\s*닫기\s*트위터\s*페이스북",
    r"공유하기\s*닫기\s*트위터\s*페이스북",
    r"등록일\s*\d{4}-\d{2}-\d{2}\s*조회\s*\d+",
    r"바로가기\s*메뉴\s*본문\s*바로가기\s*주메뉴\s*바로가기\s*푸터\s*바로가기",
    r"이전\s*글\s*다음\s*글\s*목록",
    r"※\s*입찰설명회는\s*별도\s*진행하지\s*않으며.{0,200}?변경될\s*수\s*있습니다\s*\.",
    r"바로가기\s*메뉴\s*본문\s*바로가기\s*주메뉴.*?(?=공지사항\s*상세정보\s*보기|상세정보\s*보기)",
    r"KOSA\s*Menu\s*회원가입\s*로그인\s*KOSA\s*전체메뉴.*?(?=알림마당\s*협회에서)",
    r"알림마당\s*협회에서\s*활동하고\s*있는\s*다양한\s*소식을\s*알려\s*드립니다\s*\.\s*글씨크게.*?(?=공지사항\s*상세정보|제목\s)",
    r"이용약관\s*개인정보처리방침\s*찾아오시는\s*길\s*사이트맵.*$",
    r"이전글\s*목록\s*다음글",
]


def make_readable(body: str | None) -> str:
    """본문 raw text → 마커 토큰 포함 plain text. JS가 줄별로 HTML 입힘.

    토큰:
      §§HEAD§§<line>  → 큰 헤딩 (□ ▣ ■ ▶ 또는 추출된 표 헤더). border-bottom 강조.
      §§NOTE§§<line>  → 주석 (※). 좌측 border + 회색 배경.
      그 외 일반 줄  → 들여쓰기 또는 plain.
    """
    if not body or not isinstance(body, str):
        return ""

    clean = _html.unescape(body)
    clean = clean.replace("​", "").replace("\xa0", " ")
    clean = re.sub(r"\s+", " ", clean)
    clean = re.sub(r"\[첨부 본문\]\s*", "", clean)

    for pat in _CHROME_PATTERNS:
        clean = re.sub(pat, " ", clean, flags=re.DOTALL)
    clean = re.sub(r"[=\-_*]{4,}", " ", clean)
    clean = re.sub(r"\s+", " ", clean).strip()

    # 날짜·시각·표 패턴 정규화
    clean = re.sub(r"(\d{4})\.\s+(\d{1,2})\.\s+(\d{1,2})\.", r"\1.\2.\3.", clean)
    clean = re.sub(r"(\d{1,2})\s*:\s*(\d{2})", r"\1:\2", clean)
    # 한 글자씩 띄어진 한글 표 헤더 (사 업 기 간 등) 복원
    clean = re.sub(r"(?<![가-힣])([가-힣])\s([가-힣])\s([가-힣])\s([가-힣])(?![가-힣])", r"\1\2\3\4", clean)
    clean = re.sub(r"(?<![가-힣])([가-힣])\s([가-힣])\s([가-힣])(?![가-힣])", r"\1\2\3", clean)
    # 숫자+단위 공백 제거
    clean = re.sub(
        r"(\d)\s+(년|월|일|시|분|초|개월|주|건|명|회|차|호|위|등|급|점|배|만|억|원|%|％)",
        r"\1\2", clean,
    )
    clean = re.sub(r"(\d{1,3}(?:,\d{3})+)\s+원", r"\1원", clean)
    clean = re.sub(r"\(\s+", "(", clean)
    clean = re.sub(r"\s+\)", ")", clean)
    clean = re.sub(r'"\s+', '"', clean)
    clean = re.sub(r'\s+"', '"', clean)
    clean = re.sub(r"(\d)\s+\.\s+(?=[가-힣])", r"\1. ", clean)
    clean = re.sub(r"(\d)\s+(%|％|MB|GB|TB|KB|kg|km|cm|mm)", r"\1\2", clean)

    # KISA 입찰공고 표 분해
    clean = re.sub(
        r"1\.\s*입찰에\s*부치는\s*사항\s+관리번호\s+계약건명\s+등록마감일시\s+제안서평가일\s*\(예정\)\s+입찰방법\s+",
        "\n\n§§HEAD§§□ 입찰에 부치는 사항\n",
        clean,
    )
    clean = re.sub(
        r"\s+(\d\.\s*(?:낙찰자\s*결정\s*방법|입찰\s*참가\s*자격|입찰\s*및\s*계약\s*방법|기타\s*사항|입찰\s*보증금|예정가격|제안서\s*평가)[^.①②③\n]{0,40})",
        r"\n\n§§HEAD§§\1\n",
        clean,
    )
    clean = re.sub(r"[ \t]+", " ", clean)
    clean = re.sub(r" *\n *", "\n", clean)

    # 정부 공문 마커별 줄바꿈
    clean = re.sub(r"\s*([□▣■▶])\s*", r"\n\n§§HEAD§§\1 ", clean)
    clean = re.sub(r"\s*([○●◆◇▷▸])\s*", r"\n\1 ", clean)
    clean = re.sub(r"\s*(※)\s*", r"\n§§NOTE§§\1 ", clean)
    clean = re.sub(r"\s*([①-⑳])\s*", r"\n\1 ", clean)
    clean = re.sub(r"\s+(·|‧|・)\s*", r"\n  \1 ", clean)
    # 마침표·콜론 후 한글 5자 이상 시작 → 줄바꿈
    clean = re.sub(r"([.!?])\s+(?=[가-힣A-Z][가-힣A-Z\d]{4,})", r"\1\n", clean)
    clean = re.sub(r"\n{3,}", "\n\n", clean)

    # 짧은 단편 줄 제거 (3자 이하 단순 숫자 점 등)
    lines = clean.split("\n")
    filtered = []
    for ln in lines:
        s = ln.strip()
        if not s:
            filtered.append(ln)
            continue
        # '6.', '9.', '16.', '7' 같은 의미 없는 단편
        if re.fullmatch(r"[\d.]{1,4}", s):
            continue
        filtered.append(ln)
    return "\n".join(filtered).strip()

# 빌드 출력 디렉터리 — GitHub Pages가 서빙
DEFAULT_OUT = Path(__file__).resolve().parents[1] / "site"
SRC_TEMPLATES = Path(__file__).resolve().parent / "static_templates"


def fetch_data() -> dict:
    """Supabase에서 보안 통과 announcement + score 모두 가져와 dict로 반환."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            # ⚠️ 사용자 명시 7개 source만 + 활성 공고만 (마감 미래 + 60일 내 등록 마감미명시).
            # 마감 지난 공고는 신청 불가 = 노이즈, 옛 잡 데이터 제외.
            cur.execute(
                """SELECT a.id, a.source, a.external_id, a.title, a.url, a.agency,
                          a.posted_at, a.deadline_at, a.application_start_date,
                          a.budget_mw, a.budget_period,
                          a.budget_excerpt, a.body, a.matched_keywords_json,
                          a.eligibility_status, a.eligibility_note,
                          a.attachments_json, a.ai_summary,
                          s.keyword_score, s.budget_score, s.consortium_score,
                          s.competitor_score, s.trl_score, s.total_score, s.theme_fit
                   FROM announcement a
                   LEFT JOIN score s ON s.announcement_id = a.id
                   WHERE a.is_security = TRUE AND a.is_dismissed = FALSE
                     AND a.source IN ('iitp','kisa','krit','nipa','mss','koica')
                     AND (
                       a.deadline_at >= CURRENT_DATE::text
                       OR (a.deadline_at IS NULL
                           AND a.posted_at >= (CURRENT_DATE - 60)::text)
                     )
                   ORDER BY a.posted_at DESC NULLS LAST,
                            s.total_score DESC NULLS LAST"""
            )
            rows = cur.fetchall()

    items = []
    for r in rows:
        # raw body — 디버그용으로만 (data.json에는 readable_body 만 저장)
        raw_body = r["body"] or ""
        # 가독성 처리 (정부 공문 마커 토큰 포함) — JS가 토큰 보고 HTML 입힘
        readable_body = make_readable(raw_body)[:8000]  # 8KB 상한
        # 카드 미리보기용 (마커 토큰 제거한 첫 200자)
        body_preview = re.sub(r"§§(?:HEAD|NOTE)§§", "", readable_body).replace("\n", " ").strip()[:200]
        body = readable_body  # 호환성 — 기존 코드도 body 키 참조
        try:
            mk_raw = json.loads(r["matched_keywords_json"] or "[]")
        except Exception:
            mk_raw = []
        # 카드 칩 노출용 정규화 — 별칭 통합 + 공백/대소문자 dedupe + 한글 우선
        mk = _normalize_keywords_display(mk_raw)
        try:
            atts = json.loads(r["attachments_json"] or "[]")
            # odt 중복 제거
            atts = [
                a for a in atts
                if isinstance(a, dict) and not str(a.get("name", "")).lower().endswith(".odt")
            ]
        except Exception:
            atts = []
        items.append({
            "id": r["id"],
            "source": r["source"],
            "external_id": r["external_id"],
            "title": r["title"] or "",
            "url": r["url"] or "",
            "agency": r["agency"] or "",
            "posted_at": str(r["posted_at"] or ""),
            "deadline_at": str(r["deadline_at"] or ""),
            "application_start_date": str(r["application_start_date"] or ""),
            "budget_mw": r["budget_mw"],
            "budget_period": r["budget_period"] or "",
            "budget_excerpt": r["budget_excerpt"] or "",
            "body": body,
            "body_preview": body_preview,
            "ai_summary": r["ai_summary"] or "",  # LLM 150자 요약 — 카드 본문 자리에 표시
            "matched_keywords": mk,
            "attachments": atts,
            "eligibility_status": r["eligibility_status"] or "",
            "eligibility_note": r["eligibility_note"] or "",
            "scores": {
                "keyword": float(r["keyword_score"] or 0),
                "budget": float(r["budget_score"] or 0),
                "consortium": float(r["consortium_score"] or 0),
                "competitor": float(r["competitor_score"] or 0),
                "trl": float(r["trl_score"] or 0),
                "total": float(r["total_score"] or 0),
                "theme_fit": float(r["theme_fit"] or 0),
            },
        })

    # 사이드바 필터 옵션 미리 계산
    sources_counts: dict[str, int] = {}
    today = datetime.now().date().isoformat()
    today_new_by_src: dict[str, int] = {}
    for it in items:
        sources_counts[it["source"]] = sources_counts.get(it["source"], 0) + 1
        if it["posted_at"][:10] == today:
            today_new_by_src[it["source"]] = today_new_by_src.get(it["source"], 0) + 1

    # 빌드 시각 — GitHub Actions runner는 UTC라 KST 변환해서 사용자에게 표시
    try:
        from zoneinfo import ZoneInfo
        now_kst = datetime.now(ZoneInfo("Asia/Seoul"))
    except Exception:
        from datetime import timezone, timedelta
        now_kst = datetime.now(timezone(timedelta(hours=9)))
    build_time_kst = now_kst.strftime("%Y-%m-%d %H:%M KST")

    # ── 회사 portfolio (카드 상세 "회사 매칭 강점" 자동 추출용) ──
    # profile.yaml 의 자산 데이터를 client-side JS 가 본문 매칭에 사용
    from rfp_targeter.config import profile as _profile
    p = _profile()
    company = p.get("company") or {}
    track = p.get("track_record") or {}
    ip = track.get("ip_assets") or {}
    cons = p.get("consortium") or {}
    portfolio = {
        "company": {
            "name": company.get("name", ""),
            "size": company.get("size", ""),
            "established_year": company.get("established_year"),
        },
        # 기술 자산 (트리거 키워드 + 표시명 + TRL)
        "technologies": [
            {
                "name": t.get("name", ""),
                "trl": t.get("trl"),
                "keywords": t.get("keywords") or [],
            }
            for t in (p.get("technologies") or [])
            if t.get("name")
        ],
        # 핵심 키워드 / 포지셔닝 (매칭 시 강점으로 추출)
        "core_keywords": p.get("core_keywords") or [],
        "positioning_keywords": p.get("positioning_keywords") or [],
        # 컨소시엄 자산 (학계/다기관 신호 시 표시)
        "partners": {
            "existing": [
                {
                    "name": prt.get("name", ""),
                    "type": prt.get("type", ""),
                    "evidence": prt.get("evidence", ""),
                }
                for prt in (cons.get("existing_partners") or [])
                if prt.get("name")
            ],
            "ecosystem": [
                {"name": pp.get("name", ""), "domain": pp.get("domain", "")}
                for pp in (p.get("ecosystem_partners") or [])
                if pp.get("name")
            ],
        },
        # 하이라이트 (실적·인증·표준)
        "highlights": {
            "kisa_2026_selected": "신기술" in (company.get("size", "")) or True,  # KISA 2026 신기술 선정
            "patents_total": ip.get("patents_total"),
            "patents_highlights": ip.get("patent_highlights") or [],
            "kaist_joint_patent": next(
                (h for h in (ip.get("patent_highlights") or []) if "KAIST" in h),
                None,
            ),
            "standards_total": (
                (track.get("standards") or {}).get("domestic_count", 0)
                + (track.get("standards") or {}).get("international_count", 0)
            ),
            "hacker_db_count": (track.get("data_assets") or {}).get("hacker_knowledge_db_count"),
        },
    }

    return {
        "build_time": build_time_kst,                # 사용자 표시용 KST
        "build_time_iso": datetime.now().isoformat(timespec="seconds"),  # 디버그용 UTC
        "total": len(items),
        "today_new": sum(today_new_by_src.values()),
        "sources_counts": sources_counts,
        "today_new_by_src": today_new_by_src,
        "portfolio": portfolio,
        "items": items,
    }


def write_file(out_dir: Path, name: str, content: str) -> None:
    p = out_dir / name
    p.write_text(content, encoding="utf-8")
    print(f"  wrote {p.relative_to(out_dir.parent)} ({len(content):,} chars)")


def build(out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"빌드 시작 → {out_dir}")

    # 1) 데이터 fetch
    data = fetch_data()
    print(f"  fetched {data['total']}건 (오늘 신규 {data['today_new']}건)")
    write_file(out_dir, "data.json", json.dumps(data, ensure_ascii=False, separators=(",", ":")))

    # 2) HTML / CSS / JS 템플릿 복사
    # 템플릿은 scripts/static_templates/ 에 있음
    for fname in ["index.html", "styles.css", "app.js"]:
        src = SRC_TEMPLATES / fname
        if not src.exists():
            print(f"  ⚠ 템플릿 누락: {src}")
            continue
        content = src.read_text(encoding="utf-8")
        # 빌드 시각 치환 (간단한 토큰 교체)
        content = content.replace("{{BUILD_TIME}}", data["build_time"])
        content = content.replace("{{TOTAL_COUNT}}", str(data["total"]))
        content = content.replace("{{TODAY_NEW}}", str(data["today_new"]))
        write_file(out_dir, fname, content)

    # 3) .nojekyll — GitHub Pages가 _* 파일을 무시하지 않게
    (out_dir / ".nojekyll").write_text("", encoding="utf-8")
    print("✅ 빌드 완료")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(DEFAULT_OUT), help="출력 디렉터리 (기본: ./site)")
    args = ap.parse_args()
    build(Path(args.out))


if __name__ == "__main__":
    main()
