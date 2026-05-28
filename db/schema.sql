CREATE TABLE IF NOT EXISTS api_keys (
    key TEXT PRIMARY KEY,
    uses INTEGER DEFAULT -1,
    admin INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS request_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    api_key TEXT,
    endpoint TEXT,
    model TEXT,
    stream INTEGER DEFAULT 0,
    status INTEGER DEFAULT 200,
    latency_ms INTEGER DEFAULT 0,
    error TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);
