import sqlite3
import os
import time
from flask import g
from config import DB_PATH

_schema_path = os.path.join(os.path.dirname(__file__), "schema.sql")


def _get_columns(conn, table):
    """Return set of column names for a table."""
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {r[1] for r in rows}


def _migrate(conn):
    """Add missing columns to existing tables (safe for old DBs)."""
    # --- api_keys migrations ---
    if 'name' not in _get_columns(conn, 'api_keys'):
        conn.execute("ALTER TABLE api_keys ADD COLUMN name TEXT")
    if 'created_at' not in _get_columns(conn, 'api_keys'):
        conn.execute("ALTER TABLE api_keys ADD COLUMN created_at INTEGER")
    # Fix: if created_at is TEXT (old schema), leave as-is; new inserts use INTEGER

    # Fix uses column: if it has a NOT NULL default but no actual value,
    # we can't easily ALTER. Just ensure column exists.

    # --- request_log migrations ---
    if 'ts' not in _get_columns(conn, 'request_log'):
        conn.execute("ALTER TABLE request_log ADD COLUMN ts REAL")
        # Backfill ts from existing created_at if possible
        if 'created_at' in _get_columns(conn, 'request_log'):
            try:
                conn.execute(
                    "UPDATE request_log SET ts = strftime('%s', created_at) "
                    "WHERE ts IS NULL AND created_at IS NOT NULL"
                )
            except Exception:
                # If created_at was already an integer, try direct copy
                try:
                    conn.execute(
                        "UPDATE request_log SET ts = created_at "
                        "WHERE ts IS NULL"
                    )
                except Exception:
                    pass
        # Set remaining NULL ts to current time
        conn.execute("UPDATE request_log SET ts = ? WHERE ts IS NULL", (time.time(),))

    # Create indexes if they don't exist
    try:
        conn.execute("CREATE INDEX IF NOT EXISTS idx_request_log_api_key ON request_log(api_key)")
    except Exception:
        pass
    try:
        conn.execute("CREATE INDEX IF NOT EXISTS idx_request_log_ts ON request_log(ts)")
    except Exception:
        pass

    conn.commit()


def get_db():
    """Get a SQLite connection stored in Flask g object."""
    if "db" not in g:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        g.db = conn
    return g.db


def init_db():
    """Initialize database schema and run migrations."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        # Check if tables already exist (old DB)
        existing = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}

        if 'api_keys' in existing or 'request_log' in existing:
            # Old DB — migrate first to add missing columns
            _migrate(conn)
            # Then create any new tables (IF NOT EXISTS will skip existing)
            with open(_schema_path, "r") as f:
                conn.executescript(f.read())
        else:
            # Fresh DB — just create tables
            with open(_schema_path, "r") as f:
                conn.executescript(f.read())
    finally:
        conn.close()


def close_db(exception=None):
    """Close DB connection stored in g."""
    db = g.pop("db", None)
    if db is not None:
        db.close()
