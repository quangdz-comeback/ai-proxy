import sqlite3
import os
from config import DB_PATH

_schema_path = os.path.join(os.path.dirname(__file__), "schema.sql")


def get_db():
    """Get a SQLite connection (row factory for dict-like access)."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Initialize database schema."""
    conn = get_db()
    try:
        with open(_schema_path, "r") as f:
            conn.executescript(f.read())
        conn.commit()
    finally:
        conn.close()
