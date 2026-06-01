-- RFP-Targeter PostgreSQL 스키마 (Supabase)

CREATE TABLE IF NOT EXISTS announcement (
    id TEXT PRIMARY KEY,                 -- {source}:{external_id}
    source TEXT NOT NULL,                -- iitp / ntis / kisa / kosa / nipa / krit / mss / koica / bizinfo
    external_id TEXT NOT NULL,
    title TEXT NOT NULL,
    agency TEXT,
    url TEXT NOT NULL,
    posted_at TEXT,
    deadline_at TEXT,
    budget_mw INTEGER,
    duration_months INTEGER,
    budget_period TEXT,                  -- "연간" | "총사업비" | "총 N개월" | "N차년도" | "단년" 등
    budget_excerpt TEXT,                 -- 본문 원문 발췌 (hallucination 검증용)
    budget_confidence TEXT,              -- "high" | "medium"
    summary TEXT,
    body TEXT,
    attachments_json TEXT,               -- JSON: [{name, url, local_path}]
    matched_keywords_json TEXT,          -- JSON: 보안 필터 매칭 키워드
    fetched_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    is_security BOOLEAN NOT NULL DEFAULT FALSE,
    is_dismissed BOOLEAN NOT NULL DEFAULT FALSE,
    eligibility_status TEXT,             -- 'ok'/'blocked'/'unsure'/'unknown'
    eligibility_note TEXT,
    eligibility_limit INTEGER
);

CREATE INDEX IF NOT EXISTS idx_announcement_source ON announcement(source);
CREATE INDEX IF NOT EXISTS idx_announcement_deadline ON announcement(deadline_at);
CREATE INDEX IF NOT EXISTS idx_announcement_security ON announcement(is_security);

CREATE TABLE IF NOT EXISTS score (
    announcement_id TEXT PRIMARY KEY REFERENCES announcement(id) ON DELETE CASCADE,
    keyword_score REAL,
    budget_score REAL,
    consortium_score REAL,
    competitor_score REAL,
    trl_score REAL,
    total_score REAL,
    theme_fit REAL,
    rationale_json TEXT,
    computed_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS draft (
    announcement_id TEXT PRIMARY KEY REFERENCES announcement(id) ON DELETE CASCADE,
    file_path TEXT NOT NULL,
    direction TEXT,
    status TEXT NOT NULL,
    generated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS fetch_log (
    id SERIAL PRIMARY KEY,               -- PostgreSQL: AUTOINCREMENT → SERIAL
    source TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    new_count INTEGER DEFAULT 0,
    updated_count INTEGER DEFAULT 0,
    error TEXT
);

CREATE INDEX IF NOT EXISTS idx_fetch_log_source ON fetch_log(source);

-- 범용 key-value 메타 (일일 하트비트 중복 방지 등 소량 상태 보존)
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
