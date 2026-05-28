import secrets
import sqlite3
import time
from datetime import datetime
from config import KEY_PREFIX, DB_PATH


def _get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_columns():
    """Add missing columns if upgrading from old schema."""
    conn = _get_conn()
    try:
        # Check if 'name' column exists
        cols = [r[1] for r in conn.execute("PRAGMA table_info(api_keys)").fetchall()]
        if 'name' not in cols:
            conn.execute("ALTER TABLE api_keys ADD COLUMN name TEXT")
            conn.commit()
    finally:
        conn.close()


def create_key(uses=None, admin=0, name=None, prefix=None):
    """Generate a new API key, insert into DB, return the key string.
    
    uses: None (unlimited) or positive integer. None = unlimited.
    name: optional display name. Auto-generated if not provided.
    """
    p = prefix or KEY_PREFIX
    token = secrets.token_hex(8)
    key = f"{p}-{token}"
    created_at = int(time.time())

    if not name:
        name = datetime.now().strftime("%d%m%y-%H%M%S")

    # Normalize: negative uses → None (unlimited)
    db_uses = None if (uses is None or uses < 0) else uses

    conn = _get_conn()
    try:
        conn.execute(
            "INSERT INTO api_keys (key, name, uses, admin, created_at) VALUES (?, ?, ?, ?, ?)",
            (key, name, db_uses, int(bool(admin)), created_at),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        raise ValueError(f"Name '{name}' already exists")
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


def get_key_by_name(name):
    """Return dict for the given key name, or None if not found."""
    conn = _get_conn()
    try:
        row = conn.execute("SELECT * FROM api_keys WHERE name = ?", (name,)).fetchone()
        if row:
            return dict(row)
        return None
    finally:
        conn.close()


def decrement_uses(key):
    """Decrement uses by 1 if uses > 0. Return True on success.
    If uses is NULL (unlimited), do nothing and return True."""
    conn = _get_conn()
    try:
        row = conn.execute("SELECT uses FROM api_keys WHERE key = ?", (key,)).fetchone()
        if not row:
            return False
        uses = row["uses"]
        if uses is None:
            return True  # unlimited
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
        rows = conn.execute("SELECT key, name, uses, admin, created_at FROM api_keys ORDER BY name").fetchall()
        return [{
            "name": r["name"],
            "key": r["key"],
            "uses": r["uses"],
            "admin": bool(r["admin"]),
            "created_at": r["created_at"],
        } for r in rows]
    finally:
        conn.close()


def edit_key(key, **kwargs):
    """Update key fields. Return updated row dict, or None if key not found."""
    if not kwargs:
        return None
    conn = _get_conn()
    try:
        row = conn.execute("SELECT key FROM api_keys WHERE key = ?", (key,)).fetchone()
        if not row:
            return None

        sets = []
        vals = []
        for k, v in kwargs.items():
            if v is not None:
                sets.append(f"{k} = ?")
                vals.append(v)
        if not sets:
            return None

        vals.append(key)
        conn.execute(f"UPDATE api_keys SET {', '.join(sets)} WHERE key = ?", vals)
        conn.commit()

        updated = conn.execute("SELECT key, name, uses, admin, created_at FROM api_keys WHERE key = ?", (key,)).fetchone()
        return dict(updated) if updated else None
    except sqlite3.IntegrityError:
        raise ValueError(f"Name already exists")
    finally:
        conn.close()


def delete_key(key=None, name=None):
    """Delete key by key or name. Return deleted row info or None."""
    conn = _get_conn()
    try:
        if key:
            row = conn.execute("SELECT key, name FROM api_keys WHERE key = ?", (key,)).fetchone()
        elif name:
            row = conn.execute("SELECT key, name FROM api_keys WHERE name = ?", (name,)).fetchone()
        else:
            return None

        if not row:
            return None

        conn.execute("DELETE FROM api_keys WHERE key = ?", (row["key"],))
        conn.commit()
        return {"name": row["name"], "key": row["key"]}
    finally:
        conn.close()


def log_request(api_key, endpoint, model, stream, status, latency_ms, error=None):
    """Insert a request log entry."""
    conn = _get_conn()
    try:
        conn.execute(
            "INSERT INTO request_log (ts, api_key, endpoint, model, stream, status, latency_ms, error) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (time.time(), api_key, endpoint, model, int(stream), status, latency_ms, error),
        )
        conn.commit()
    finally:
        conn.close()


def get_logs(limit=50, api_key=None):
    """Get request logs, optionally filtered by api_key."""
    conn = _get_conn()
    try:
        if api_key:
            rows = conn.execute(
                "SELECT * FROM request_log WHERE api_key = ? ORDER BY id DESC LIMIT ?",
                (api_key, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM request_log ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
