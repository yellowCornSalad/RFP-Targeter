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
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rfp_targeter.db.models import get_conn  # noqa: E402

# 빌드 출력 디렉터리 — GitHub Pages가 서빙
DEFAULT_OUT = Path(__file__).resolve().parents[1] / "site"
SRC_TEMPLATES = Path(__file__).resolve().parent / "static_templates"


def fetch_data() -> dict:
    """Supabase에서 보안 통과 announcement + score 모두 가져와 dict로 반환."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT a.id, a.source, a.external_id, a.title, a.url, a.agency,
                          a.posted_at, a.deadline_at, a.budget_mw, a.budget_period,
                          a.budget_excerpt, a.body, a.matched_keywords_json,
                          a.eligibility_status, a.eligibility_note,
                          a.attachments_json,
                          s.keyword_score, s.budget_score, s.consortium_score,
                          s.competitor_score, s.trl_score, s.total_score, s.theme_fit
                   FROM announcement a
                   LEFT JOIN score s ON s.announcement_id = a.id
                   WHERE a.is_security = TRUE AND a.is_dismissed = FALSE
                   ORDER BY a.posted_at DESC NULLS LAST,
                            s.total_score DESC NULLS LAST"""
            )
            rows = cur.fetchall()

    items = []
    for r in rows:
        # 본문은 너무 길어서 카드 미리보기용으로 정제 + 잘라서 저장
        body = (r["body"] or "")[:3000]
        try:
            mk = json.loads(r["matched_keywords_json"] or "[]")
        except Exception:
            mk = []
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
            "budget_mw": r["budget_mw"],
            "budget_period": r["budget_period"] or "",
            "budget_excerpt": r["budget_excerpt"] or "",
            "body": body,
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

    return {
        "build_time": datetime.now().isoformat(timespec="seconds"),
        "total": len(items),
        "today_new": sum(today_new_by_src.values()),
        "sources_counts": sources_counts,
        "today_new_by_src": today_new_by_src,
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
