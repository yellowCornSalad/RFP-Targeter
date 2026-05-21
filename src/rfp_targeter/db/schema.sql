-- RFP-Targeter SQLite 스키마

CREATE TABLE IF NOT EXISTS announcement (
    id TEXT PRIMARY KEY,                -- {source}:{external_id} 형태
    source TEXT NOT NULL,               -- iitp / ntis / kisa / krit / bizinfo
    external_id TEXT NOT NULL,          -- 사이트 측 공고 ID
    title TEXT NOT NULL,
    agency TEXT,                        -- 발주 기관
    url TEXT NOT NULL,
    posted_at TEXT,                     -- ISO 8601
    deadline_at TEXT,                   -- ISO 8601
    budget_mw INTEGER,                  -- 단위: 백만원, 불명이면 NULL
    duration_months INTEGER,
    summary TEXT,
    body TEXT,                          -- 전체 본문
    attachments_json TEXT,              -- [{name, url, local_path}]
    matched_keywords_json TEXT,         -- 필터링 통과 시 매칭된 키워드
    fetched_at TEXT NOT NULL,           -- 최초 수집
    updated_at TEXT NOT NULL,
    is_security INTEGER NOT NULL DEFAULT 0,  -- 보안 키워드 통과 여부
    is_dismissed INTEGER NOT NULL DEFAULT 0, -- 사용자가 '관심없음' 표시
    eligibility_status TEXT,                 -- 'ok'/'blocked'/'unsure'/'unknown' (filters/eligibility.py)
    eligibility_note TEXT,                   -- 사용자 표시용 한 줄
    eligibility_limit INTEGER                -- 추출된 N년 (없으면 NULL)
);

CREATE INDEX IF NOT EXISTS idx_announcement_source ON announcement(source);
CREATE INDEX IF NOT EXISTS idx_announcement_deadline ON announcement(deadline_at);
CREATE INDEX IF NOT EXISTS idx_announcement_security ON announcement(is_security);

CREATE TABLE IF NOT EXISTS score (
    announcement_id TEXT PRIMARY KEY REFERENCES announcement(id) ON DELETE CASCADE,
    keyword_score REAL,                 -- 0~100
    budget_score REAL,
    consortium_score REAL,
    competitor_score REAL,
    trl_score REAL,
    total_score REAL,                   -- 가중 합산
    theme_fit REAL,                     -- 별도: 회사 테마 적합도(0~100)
    rationale_json TEXT,                -- {keyword: ["근거1","근거2"], ...}
    computed_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS draft (
    announcement_id TEXT PRIMARY KEY REFERENCES announcement(id) ON DELETE CASCADE,
    file_path TEXT NOT NULL,            -- drafts/{id}.md
    direction TEXT,                     -- 선택된 차별화 방향 (브레인스토밍 결과)
    status TEXT NOT NULL,               -- pending / generated / reviewed
    generated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS fetch_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    new_count INTEGER DEFAULT 0,
    updated_count INTEGER DEFAULT 0,
    error TEXT
);

CREATE INDEX IF NOT EXISTS idx_fetch_log_source ON fetch_log(source);
