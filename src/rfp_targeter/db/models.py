"""경량 SQLite wrapper. ORM 없이 dict 기반으로 처리."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from rfp_targeter.config import db_path

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def get_conn() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))


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
    summary: str | None = None
    body: str | None = None
    attachments: list[dict] = field(default_factory=list)
    matched_keywords: list[str] = field(default_factory=list)
    is_security: bool = False

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


def upsert_announcement(conn: sqlite3.Connection, a: Announcement) -> bool:
    """신규면 True 반환."""
    row = conn.execute("SELECT id FROM announcement WHERE id=?", (a.id,)).fetchone()
    now = _now()
    if row is None:
        conn.execute(
            """
            INSERT INTO announcement(
                id, source, external_id, title, agency, url,
                posted_at, deadline_at, budget_mw, duration_months,
                summary, body, attachments_json, matched_keywords_json,
                fetched_at, updated_at, is_security
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                a.id, a.source, a.external_id, a.title, a.agency, a.url,
                a.posted_at, a.deadline_at, a.budget_mw, a.duration_months,
                a.summary, a.body,
                json.dumps(a.attachments, ensure_ascii=False),
                json.dumps(a.matched_keywords, ensure_ascii=False),
                now, now, int(a.is_security),
            ),
        )
        return True
    conn.execute(
        """
        UPDATE announcement SET
            title=?, agency=?, url=?, posted_at=?, deadline_at=?,
            budget_mw=?, duration_months=?, summary=?, body=?,
            attachments_json=?, matched_keywords_json=?,
            updated_at=?, is_security=?
        WHERE id=?
        """,
        (
            a.title, a.agency, a.url, a.posted_at, a.deadline_at,
            a.budget_mw, a.duration_months, a.summary, a.body,
            json.dumps(a.attachments, ensure_ascii=False),
            json.dumps(a.matched_keywords, ensure_ascii=False),
            now, int(a.is_security), a.id,
        ),
    )
    return False


def upsert_score(conn: sqlite3.Connection, s: Score) -> None:
    conn.execute(
        """
        INSERT INTO score(
            announcement_id, keyword_score, budget_score, consortium_score,
            competitor_score, trl_score, total_score, theme_fit,
            rationale_json, computed_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(announcement_id) DO UPDATE SET
            keyword_score=excluded.keyword_score,
            budget_score=excluded.budget_score,
            consortium_score=excluded.consortium_score,
            competitor_score=excluded.competitor_score,
            trl_score=excluded.trl_score,
            total_score=excluded.total_score,
            theme_fit=excluded.theme_fit,
            rationale_json=excluded.rationale_json,
            computed_at=excluded.computed_at
        """,
        (
            s.announcement_id, s.keyword_score, s.budget_score, s.consortium_score,
            s.competitor_score, s.trl_score, s.total_score, s.theme_fit,
            json.dumps(s.rationale, ensure_ascii=False),
            _now(),
        ),
    )


def log_fetch_start(conn: sqlite3.Connection, source: str) -> int:
    cur = conn.execute(
        "INSERT INTO fetch_log(source, started_at) VALUES (?,?)",
        (source, _now()),
    )
    return cur.lastrowid


def log_fetch_finish(
    conn: sqlite3.Connection, log_id: int, new_count: int, updated_count: int, error: str | None = None
) -> None:
    conn.execute(
        "UPDATE fetch_log SET finished_at=?, new_count=?, updated_count=?, error=? WHERE id=?",
        (_now(), new_count, updated_count, error, log_id),
    )


def list_security_announcements(
    conn: sqlite3.Connection,
    limit: int = 200,
    include_dismissed: bool = False,
) -> list[sqlite3.Row]:
    """보안 분류된 공고 조회.

    include_dismissed=True 면 숨김 처리(`is_dismissed=1`)된 공고도 함께 반환.
    이때 대시보드는 `is_dismissed` 컬럼 값을 보고 카드 표시/숨김 해제 액션을 분기.
    """
    dismiss_clause = "" if include_dismissed else "AND a.is_dismissed = 0"
    return conn.execute(
        f"""
        SELECT a.*, s.total_score, s.theme_fit, s.keyword_score, s.budget_score,
               s.consortium_score, s.competitor_score, s.trl_score, s.rationale_json
        FROM announcement a
        LEFT JOIN score s ON s.announcement_id = a.id
        WHERE a.is_security = 1 {dismiss_clause}
        ORDER BY COALESCE(s.total_score, 0) DESC, a.posted_at DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
