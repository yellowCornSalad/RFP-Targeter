"""1회성: 기존 SQLite DB 의 모든 데이터를 Supabase PostgreSQL 로 이전.

전제:
  - config/secrets.yaml 에 supabase.database_url 설정 완료
  - 기존 data/rfp.db (SQLite) 존재
  - Supabase 프로젝트가 Healthy 상태

사용:
  python scripts/migrate_sqlite_to_postgres.py

이후 SQLite 파일은 백업 차원에서 유지 권장.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rfp_targeter.config import db_path  # noqa: E402
from rfp_targeter.db.models import get_conn, init_db  # noqa: E402


def _truthy(v):
    """SQLite의 0/1 → Python bool. None은 False."""
    if v in (None, 0, "0", False):
        return False
    return True


def main():
    sqlite_path = db_path()
    if not sqlite_path.exists():
        print(f"SQLite 파일 없음: {sqlite_path}")
        print("이미 PostgreSQL only로 운영 중이면 이 스크립트 무시 가능.")
        return

    print(f"SQLite source: {sqlite_path}")

    # PostgreSQL 초기화
    print("Supabase 스키마 생성 중...")
    init_db()
    print("스키마 OK")

    # SQLite 열기
    sq = sqlite3.connect(sqlite_path)
    sq.row_factory = sqlite3.Row

    counts = {"announcement": 0, "score": 0, "score_skip": 0, "fetch_log": 0}

    # 1. announcement (자체 트랜잭션 — score 보다 먼저 commit 되어야 FK 검증 통과)
    print("\n[1/3] announcement 마이그레이션...")
    with get_conn() as pg:
        with pg.cursor() as pc:
            ann_rows = sq.execute("SELECT * FROM announcement").fetchall()
            for r in ann_rows:
                pc.execute(
                    """
                    INSERT INTO announcement(
                        id, source, external_id, title, agency, url,
                        posted_at, deadline_at, budget_mw, duration_months,
                        summary, body, attachments_json, matched_keywords_json,
                        fetched_at, updated_at, is_security, is_dismissed,
                        eligibility_status, eligibility_note, eligibility_limit
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    (
                        r["id"], r["source"], r["external_id"], r["title"],
                        r["agency"], r["url"],
                        r["posted_at"], r["deadline_at"],
                        r["budget_mw"], r["duration_months"],
                        r["summary"], r["body"],
                        r["attachments_json"], r["matched_keywords_json"],
                        r["fetched_at"], r["updated_at"],
                        _truthy(r["is_security"]), _truthy(r["is_dismissed"]),
                        r["eligibility_status"] if "eligibility_status" in r.keys() else None,
                        r["eligibility_note"]   if "eligibility_note"   in r.keys() else None,
                        r["eligibility_limit"]  if "eligibility_limit"  in r.keys() else None,
                    ),
                )
                counts["announcement"] += 1
                if counts["announcement"] % 200 == 0:
                    print(f"  ... {counts['announcement']:,}건")
    print(f"  완료: {counts['announcement']:,}건 (커밋됨)")

    # 2. score (announcement 가 모두 commit된 뒤 시작 — FK 검증 통과)
    # 그래도 mock 등 announcement 없는 orphan score는 개별 try/except로 skip
    print("\n[2/3] score 마이그레이션...")
    with get_conn() as pg:
        sc_rows = sq.execute("SELECT * FROM score").fetchall()
        for r in sc_rows:
            try:
                with pg.cursor() as pc:
                    pc.execute(
                        """
                        INSERT INTO score(
                            announcement_id, keyword_score, budget_score, consortium_score,
                            competitor_score, trl_score, total_score, theme_fit,
                            rationale_json, computed_at
                        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                        ON CONFLICT (announcement_id) DO NOTHING
                        """,
                        (
                            r["announcement_id"], r["keyword_score"], r["budget_score"],
                            r["consortium_score"], r["competitor_score"], r["trl_score"],
                            r["total_score"], r["theme_fit"],
                            r["rationale_json"], r["computed_at"],
                        ),
                    )
                pg.commit()  # 각 row 별 commit (FK 위반 시 1건만 영향)
                counts["score"] += 1
            except Exception as e:
                pg.rollback()
                counts["score_skip"] += 1
                if counts["score_skip"] <= 3:
                    print(f"  skip {r['announcement_id']}: {str(e)[:60]}")
    print(f"  완료: {counts['score']:,}건  (skip {counts['score_skip']}건 — orphan FK)")

    # 3. fetch_log (선택)
    print("\n[3/3] fetch_log 마이그레이션...")
    with get_conn() as pg:
        with pg.cursor() as pc:
            try:
                fl_rows = sq.execute("SELECT * FROM fetch_log").fetchall()
                for r in fl_rows:
                    pc.execute(
                        """
                        INSERT INTO fetch_log(source, started_at, finished_at,
                                              new_count, updated_count, error)
                        VALUES (%s,%s,%s,%s,%s,%s)
                        """,
                        (r["source"], r["started_at"], r["finished_at"],
                         r["new_count"], r["updated_count"], r["error"]),
                    )
                    counts["fetch_log"] += 1
                print(f"  완료: {counts['fetch_log']:,}건")
            except Exception as e:
                print(f"  skip (선택): {e}")

    sq.close()

    print(f"\n=== 마이그레이션 완료 ===")
    for t, n in counts.items():
        print(f"  {t:<15}  {n:>5,}건")
    print("\nSupabase 대시보드 Table Editor에서 확인 가능.")


if __name__ == "__main__":
    main()
