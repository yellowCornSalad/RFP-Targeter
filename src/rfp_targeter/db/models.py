"""PostgreSQL (Supabase) wrapper — psycopg3 기반.

이전 SQLite 버전에서 마이그레이션:
- placeholder ? → %s
- INTEGER(0/1) → BOOLEAN
- AUTOINCREMENT → SERIAL
- sqlite3.Row → psycopg dict_row (sqlite3.Row와 동일 인터페이스 [key]/get())
- executescript → 직접 execute (psycopg는 multi-statement OK)
- ALTER TABLE 마이그레이션 그대로 (psycopg도 IF NOT EXISTS 미지원)
"""
from __future__ import annotations

import json
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

import psycopg
from psycopg.rows import dict_row

from rfp_targeter.config import db_url

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def get_conn() -> Iterator[psycopg.Connection]:
    """PostgreSQL 연결. dict_row로 row를 dict처럼.

    prepare_threshold=None: Supabase transaction pooler(pgbouncer)는
    prepared statement를 트랜잭션 간 재사용 못함 → DuplicatePreparedStatement
    에러 발생. None으로 prepared 비활성화 (성능 영향 미미).
    """
    conn = psycopg.connect(
        db_url(),
        row_factory=dict_row,
        autocommit=False,
        prepare_threshold=None,
    )
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    """schema.sql 실행 + 추가 컬럼 마이그레이션."""
    with get_conn() as conn:
        schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")
        # psycopg는 multi-statement를 한 번에 execute 가능
        with conn.cursor() as cur:
            cur.execute(schema_sql)
        # 옛 DB에 컬럼이 없을 때 추가 (이미 있으면 ProgrammingError → 무시)
        for ddl in [
            "ALTER TABLE announcement ADD COLUMN IF NOT EXISTS eligibility_status TEXT",
            "ALTER TABLE announcement ADD COLUMN IF NOT EXISTS eligibility_note TEXT",
            "ALTER TABLE announcement ADD COLUMN IF NOT EXISTS eligibility_limit INTEGER",
            "ALTER TABLE announcement ADD COLUMN IF NOT EXISTS budget_period TEXT",
            "ALTER TABLE announcement ADD COLUMN IF NOT EXISTS budget_excerpt TEXT",
            "ALTER TABLE announcement ADD COLUMN IF NOT EXISTS budget_confidence TEXT",
        ]:
            try:
                with conn.cursor() as cur:
                    cur.execute(ddl)
            except psycopg.Error:
                pass  # 이미 컬럼 존재 또는 동시 마이그레이션


# ---------- 도메인 dataclass ----------


@dataclass
class Announcement:
    source: str
    external_id: str
    title: str
    url: str
    agency: str | None = None
    posted_at: str | None = None
    deadline_at: str | None = None
    budget_mw: int | None = None
    duration_months: int | None = None
    budget_period: str | None = None       # "연간" | "총사업비" | "총 N개월" | "N차년도"
    budget_excerpt: str | None = None      # 본문 원문 발췌 (hallucination 검증)
    budget_confidence: str | None = None   # "high" | "medium"
    summary: str | None = None
    body: str | None = None
    attachments: list[dict] = field(default_factory=list)
    matched_keywords: list[str] = field(default_factory=list)
    is_security: bool = False
    eligibility_status: str | None = None
    eligibility_note: str | None = None
    eligibility_limit: int | None = None

    @property
    def id(self) -> str:
        return f"{self.source}:{self.external_id}"


@dataclass
class Score:
    announcement_id: str
    keyword_score: float
    budget_score: float
    consortium_score: float
    competitor_score: float
    trl_score: float
    total_score: float
    theme_fit: float
    rationale: dict


# ---------- repository 함수들 ----------


def upsert_announcement(conn: psycopg.Connection, a: Announcement) -> bool:
    """신규면 True, 업데이트면 False."""
    now = _now()
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM announcement WHERE id = %s", (a.id,))
        exists = cur.fetchone() is not None
        if not exists:
            cur.execute(
                """
                INSERT INTO announcement(
                    id, source, external_id, title, agency, url,
                    posted_at, deadline_at, budget_mw, duration_months,
                    budget_period, budget_excerpt, budget_confidence,
                    summary, body, attachments_json, matched_keywords_json,
                    fetched_at, updated_at, is_security,
                    eligibility_status, eligibility_note, eligibility_limit
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                (
                    a.id, a.source, a.external_id, a.title, a.agency, a.url,
                    a.posted_at, a.deadline_at, a.budget_mw, a.duration_months,
                    a.budget_period, a.budget_excerpt, a.budget_confidence,
                    a.summary, a.body,
                    json.dumps(a.attachments, ensure_ascii=False),
                    json.dumps(a.matched_keywords, ensure_ascii=False),
                    now, now, bool(a.is_security),
                    a.eligibility_status, a.eligibility_note, a.eligibility_limit,
                ),
            )
            return True
        cur.execute(
            """
            UPDATE announcement SET
                title=%s, agency=%s, url=%s, posted_at=%s, deadline_at=%s,
                budget_mw=%s, duration_months=%s,
                budget_period=%s, budget_excerpt=%s, budget_confidence=%s,
                summary=%s, body=%s,
                attachments_json=%s, matched_keywords_json=%s,
                updated_at=%s, is_security=%s,
                eligibility_status=%s, eligibility_note=%s, eligibility_limit=%s
            WHERE id=%s
            """,
            (
                a.title, a.agency, a.url, a.posted_at, a.deadline_at,
                a.budget_mw, a.duration_months,
                a.budget_period, a.budget_excerpt, a.budget_confidence,
                a.summary, a.body,
                json.dumps(a.attachments, ensure_ascii=False),
                json.dumps(a.matched_keywords, ensure_ascii=False),
                now, bool(a.is_security),
                a.eligibility_status, a.eligibility_note, a.eligibility_limit,
                a.id,
            ),
        )
        return False


def upsert_score(conn: psycopg.Connection, s: Score) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO score(
                announcement_id, keyword_score, budget_score, consortium_score,
                competitor_score, trl_score, total_score, theme_fit,
                rationale_json, computed_at
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT(announcement_id) DO UPDATE SET
                keyword_score=EXCLUDED.keyword_score,
                budget_score=EXCLUDED.budget_score,
                consortium_score=EXCLUDED.consortium_score,
                competitor_score=EXCLUDED.competitor_score,
                trl_score=EXCLUDED.trl_score,
                total_score=EXCLUDED.total_score,
                theme_fit=EXCLUDED.theme_fit,
                rationale_json=EXCLUDED.rationale_json,
                computed_at=EXCLUDED.computed_at
            """,
            (
                s.announcement_id, s.keyword_score, s.budget_score, s.consortium_score,
                s.competitor_score, s.trl_score, s.total_score, s.theme_fit,
                json.dumps(s.rationale, ensure_ascii=False),
                _now(),
            ),
        )


def log_fetch_start(conn: psycopg.Connection, source: str) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO fetch_log(source, started_at) VALUES (%s, %s) RETURNING id",
            (source, _now()),
        )
        row = cur.fetchone()
        return int(row["id"]) if row else 0


def log_fetch_finish(
    conn: psycopg.Connection, log_id: int, new_count: int, updated_count: int,
    error: str | None = None,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE fetch_log SET finished_at=%s, new_count=%s, updated_count=%s, error=%s WHERE id=%s",
            (_now(), new_count, updated_count, error, log_id),
        )


def list_security_announcements(
    conn: psycopg.Connection,
    limit: int = 200,
    include_dismissed: bool = False,
) -> list[dict]:
    """보안 분류된 공고 조회.

    PostgreSQL은 BOOLEAN이라 is_security = TRUE / is_dismissed = FALSE 사용.
    Row는 psycopg dict_row 로 dict 형태 반환 (sqlite3.Row와 인터페이스 호환).
    """
    dismiss_clause = "" if include_dismissed else "AND a.is_dismissed = FALSE"
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT a.*, s.total_score, s.theme_fit, s.keyword_score, s.budget_score,
                   s.consortium_score, s.competitor_score, s.trl_score, s.rationale_json
            FROM announcement a
            LEFT JOIN score s ON s.announcement_id = a.id
            WHERE a.is_security = TRUE {dismiss_clause}
            ORDER BY COALESCE(s.total_score, 0) DESC, a.posted_at DESC
            LIMIT %s
            """,
            (limit,),
        )
        return cur.fetchall()
