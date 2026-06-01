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
    """schema.sql 실행 + 추가 컬럼/테이블 마이그레이션.

    ⚠️ 각 마이그레이션은 '독립 트랜잭션'(fresh connection)으로 실행.
    이유: Supabase pgbouncer(transaction pooler)에서 multi-statement
    cur.execute(schema_sql) 가 트랜잭션을 abort 시키면, 같은 트랜잭션 안의
    후속 DDL 이 전부 InFailedSqlTransaction 으로 조용히 swallow 되고
    commit 이 rollback 으로 끝나 새 테이블(meta 등)이 누락되던 버그.
    DDL 마다 별도 get_conn() 으로 분리해 서로 영향 없게 한다.
    """
    with get_conn() as conn:
        schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")
        with conn.cursor() as cur:
            cur.execute(schema_sql)
    # 옛 DB 대상 개별 마이그레이션 — 각각 독립 트랜잭션 (상호 격리)
    for ddl in [
        "ALTER TABLE announcement ADD COLUMN IF NOT EXISTS eligibility_status TEXT",
        "ALTER TABLE announcement ADD COLUMN IF NOT EXISTS eligibility_note TEXT",
        "ALTER TABLE announcement ADD COLUMN IF NOT EXISTS eligibility_limit INTEGER",
        "ALTER TABLE announcement ADD COLUMN IF NOT EXISTS budget_period TEXT",
        "ALTER TABLE announcement ADD COLUMN IF NOT EXISTS budget_excerpt TEXT",
        "ALTER TABLE announcement ADD COLUMN IF NOT EXISTS budget_confidence TEXT",
        # LLM 맥락 판단 결과(도메인 적합성 + TRL 단계) JSON 캐시 — assess_contents.py
        "ALTER TABLE announcement ADD COLUMN IF NOT EXISTS llm_assess_json TEXT",
        # meta KV (일일 하트비트 dedup 등) — 새 테이블도 개별 DDL 로 보장
        "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)",
    ]:
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(ddl)
        except psycopg.Error:
            pass  # 이미 컬럼/테이블 존재 또는 동시 마이그레이션


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
    application_start_date: str | None = None   # MSS API의 applicationStartDate (신청 시작일)

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
                    posted_at, deadline_at, application_start_date,
                    budget_mw, duration_months,
                    budget_period, budget_excerpt, budget_confidence,
                    summary, body, attachments_json, matched_keywords_json,
                    fetched_at, updated_at, is_security,
                    eligibility_status, eligibility_note, eligibility_limit
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                (
                    a.id, a.source, a.external_id, a.title, a.agency, a.url,
                    a.posted_at, a.deadline_at, a.application_start_date,
                    a.budget_mw, a.duration_months,
                    a.budget_period, a.budget_excerpt, a.budget_confidence,
                    a.summary, a.body,
                    json.dumps(a.attachments, ensure_ascii=False),
                    json.dumps(a.matched_keywords, ensure_ascii=False),
                    now, now, bool(a.is_security),
                    a.eligibility_status, a.eligibility_note, a.eligibility_limit,
                ),
            )
            return True
        # UPDATE — 빈 값으로 기존 데이터 덮어쓰지 않게 COALESCE 가드:
        # · attachments_json : 새로 추출 실패해도 (= []) 기존 첨부 유지
        # · budget_mw / period / excerpt : 새 추출 실패해도 기존 값 유지
        # · body : 빈 문자열이면 기존 본문 유지
        # (크롤러가 일시적으로 fetch 실패하거나 사이트 구조 변경 시 데이터 보존)
        # 가드 강화: a.attachments가 None/빈/[Falsy]든 모두 '[]' 로 정규화 후 CASE WHEN.
        # IS NULL / 'null' 문자열 / 빈 dict 등 엣지 케이스도 보호.
        if not a.attachments or not isinstance(a.attachments, list):
            attachments_str = "[]"
        else:
            # 빈 dict 만 있는 리스트도 빈 취급
            real_atts = [x for x in a.attachments if isinstance(x, dict) and x.get("name")]
            attachments_str = json.dumps(real_atts, ensure_ascii=False) if real_atts else "[]"
        cur.execute(
            """
            UPDATE announcement SET
                title=%s, agency=%s, url=%s, posted_at=%s, deadline_at=%s,
                application_start_date=COALESCE(%s, application_start_date),
                budget_mw=COALESCE(%s, budget_mw),
                duration_months=COALESCE(%s, duration_months),
                budget_period=COALESCE(%s, budget_period),
                budget_excerpt=COALESCE(%s, budget_excerpt),
                budget_confidence=COALESCE(%s, budget_confidence),
                summary=COALESCE(NULLIF(%s,''), summary),
                body=COALESCE(NULLIF(%s,''), body),
                attachments_json = CASE
                    WHEN %s IN ('','[]') THEN attachments_json
                    ELSE %s
                END,
                matched_keywords_json=%s,
                updated_at=%s, is_security=%s,
                eligibility_status=COALESCE(%s, eligibility_status),
                eligibility_note=COALESCE(%s, eligibility_note),
                eligibility_limit=COALESCE(%s, eligibility_limit)
            WHERE id=%s
            """,
            (
                a.title, a.agency, a.url, a.posted_at, a.deadline_at,
                a.application_start_date,
                a.budget_mw, a.duration_months,
                a.budget_period, a.budget_excerpt, a.budget_confidence,
                a.summary, a.body,
                attachments_str, attachments_str,
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


def meta_get(conn: psycopg.Connection, key: str) -> str | None:
    """meta KV 조회. 없으면 None."""
    with conn.cursor() as cur:
        cur.execute("SELECT value FROM meta WHERE key=%s", (key,))
        row = cur.fetchone()
        return row["value"] if row else None


def meta_set(conn: psycopg.Connection, key: str, value: str) -> None:
    """meta KV 저장 (upsert)."""
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO meta(key, value) VALUES (%s, %s) "
            "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
            (key, value),
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
