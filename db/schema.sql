-- Stock Sentinel database schema

-- ── Pipeline run bookkeeping ─────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS run_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_date    TEXT    NOT NULL,
    status      TEXT    NOT NULL DEFAULT 'running',   -- running | complete | error
    error_msg   TEXT,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- ── Legacy mention table (kept for backwards-compat) ─────────────────────────
CREATE TABLE IF NOT EXISTS ticker_mentions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          INTEGER NOT NULL REFERENCES run_log(id),
    ticker          TEXT    NOT NULL,
    mentions        INTEGER NOT NULL,
    subreddits_seen TEXT,
    last_seen_utc   TEXT,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- ── Reddit mention counts per daily run ──────────────────────────────────────
CREATE TABLE IF NOT EXISTS reddit_mentions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_date        TEXT    NOT NULL,
    ticker          TEXT    NOT NULL,
    mention_count   INTEGER NOT NULL DEFAULT 0,
    sentiment_words TEXT,                              -- JSON array of matched sentiment keywords
    created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE(run_date, ticker)
);

-- ── Financial data cache (fundamentals + news) ────────────────────────────────
CREATE TABLE IF NOT EXISTS research_cache (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker      TEXT    NOT NULL,
    data_type   TEXT    NOT NULL,   -- 'fundamentals' | 'news'
    data_json   TEXT    NOT NULL,
    fetched_at  TEXT    NOT NULL,
    expires_at  TEXT    NOT NULL,
    UNIQUE(ticker, data_type)
);

-- ── Full analysis results per daily run ──────────────────────────────────────
CREATE TABLE IF NOT EXISTS daily_results (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    run_date            TEXT    NOT NULL,
    ticker              TEXT    NOT NULL,
    composite_score     REAL,
    recommendation      TEXT,
    score_news          REAL,
    score_buffett       REAL,
    score_thesis        REAL,
    score_critique      REAL,
    score_contracts     REAL,
    score_pnl           REAL,
    score_politicians   REAL,
    score_competitors   REAL,
    price_at_analysis   REAL,
    full_analysis_json  TEXT,
    created_at          TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE(run_date, ticker)
);

-- ── Legacy deep-analysis table ───────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS ticker_analysis (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id               INTEGER NOT NULL REFERENCES run_log(id),
    ticker               TEXT    NOT NULL,
    company_name         TEXT,
    overall_score        INTEGER,
    recommendation       TEXT,
    thesis               TEXT,
    bull_case            TEXT,
    bear_case            TEXT,
    key_risks            TEXT,
    catalysts            TEXT,
    price_target_rationale TEXT,
    price_change_30d_pct REAL,
    input_tokens         INTEGER,
    output_tokens        INTEGER,
    error                TEXT,
    created_at           TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- ── Final top-N picks per run ────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS final_picks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id      INTEGER NOT NULL REFERENCES run_log(id),
    ticker      TEXT    NOT NULL,
    rank        INTEGER NOT NULL,
    score       INTEGER NOT NULL,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_mentions_run     ON ticker_mentions(run_id);
CREATE INDEX IF NOT EXISTS idx_analysis_run     ON ticker_analysis(run_id);
CREATE INDEX IF NOT EXISTS idx_picks_run        ON final_picks(run_id);
CREATE INDEX IF NOT EXISTS idx_cache_lookup     ON research_cache(ticker, data_type);
CREATE INDEX IF NOT EXISTS idx_cache_expires    ON research_cache(expires_at);
CREATE INDEX IF NOT EXISTS idx_reddit_date      ON reddit_mentions(run_date);
CREATE INDEX IF NOT EXISTS idx_results_date     ON daily_results(run_date);
