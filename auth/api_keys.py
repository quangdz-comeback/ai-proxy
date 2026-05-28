import secrets
import sqlite3
from config import KEY_PREFIX, DB_PATH


def _get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def create_key(uses=-1, admin=0, prefix=None):
    """Generate a new API key, insert into DB, return the key string."""
    p = prefix or KEY_PREFIX
    token = secrets.token_hex(16)
    key = f"{p}-{token}"
    conn = _get_conn()
    try:
        conn.execute(
            "INSERT INTO api_keys (key, uses, admin) VALUES (?, ?, ?)",
            (key, uses, admin),
        )
        conn.commit()
    finally:
        conn.close()
    return key


def get_key(key):
    """Return dict for the given key, or None if not found."""
    conn = _get_conn()
    try:
        row = conn.execute("SELECT * FROM api_keys WHERE key = ?", (key,)).fetchone()
        if row:
            return dict(row)
        return None
    finally:
        conn.close()


def decrement_uses(key):
    """Decrement uses by 1 if uses > 0. Return True on success.
    If uses == -1 (unlimited), do nothing and return True."""
    conn = _get_conn()
    try:
        row = conn.execute("SELECT uses FROM api_keys WHERE key = ?", (key,)).fetchone()
        if not row:
            return False
        uses = row["uses"]
        if uses == -1:
            return True
        if uses <= 0:
            return False
        conn.execute("UPDATE api_keys SET uses = uses - 1 WHERE key = ?", (key,))
        conn.commit()
        return True
    finally:
        conn.close()


def list_keys():
    """Return a list of dicts for all API keys."""
    conn = _get_conn()
    try:
        rows = conn.execute("SELECT * FROM api_keys ORDER BY created_at DESC").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def edit_key(key, **kwargs):
    """Update key fields. Return True if updated, False if key not found."""
    if not kwargs:
        return False
    conn = _get_conn()
    try:
        row = conn.execute("SELECT key FROM api_keys WHERE key = ?", (key,)).fetchone()
        if not row:
            return False
        sets = []
        vals = []
        for k, v in kwargs.items():
            sets.append(f"{k} = ?")
            vals.append(v)
        vals.append(key)
        conn.execute(f"UPDATE api_keys SET {', '.join(sets)} WHERE key = ?", vals)
        conn.commit()
        return True
    finally:
        conn.close()


def delete_key(key):
    """Delete key. Return True if deleted, False if key not found."""
    conn = _get_conn()
    try:
        cursor = conn.execute("DELETE FROM api_keys WHERE key = ?", (key,))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def log_request(api_key, endpoint, model, stream, status, latency_ms, error=None):
    """Insert a request log entry."""
    conn = _get_conn()
    try:
        conn.execute(
            "INSERT INTO request_log (api_key, endpoint, model, stream, status, latency_ms, error) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (api_key, endpoint, model, int(stream), status, latency_ms, error),
        )
        conn.commit()
    finally:
        conn.close()
