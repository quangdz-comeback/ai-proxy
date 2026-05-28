CREATE TABLE IF NOT EXISTS api_keys (
    key TEXT PRIMARY KEY,
    name TEXT UNIQUE,
    uses INTEGER,
    admin INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS request_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    api_key TEXT,
    endpoint TEXT NOT NULL,
    model TEXT,
    stream INTEGER,
    status INTEGER,
    latency_ms INTEGER,
    error TEXT
);

CREATE INDEX IF NOT EXISTS idx_request_log_api_key ON request_log(api_key);
CREATE INDEX IF NOT EXISTS idx_request_log_ts ON request_log(ts);
