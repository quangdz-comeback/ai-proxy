import sqlite3
import os
from flask import g
from config import DB_PATH

_schema_path = os.path.join(os.path.dirname(__file__), "schema.sql")


def get_db():
    """Get a SQLite connection stored in Flask g object."""
    if "db" not in g:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        g.db = conn
    return g.db


def init_db():
    """Initialize database schema (can run outside app context)."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        with open(_schema_path, "r") as f:
            conn.executescript(f.read())
        conn.commit()
    finally:
        conn.close()


def close_db(exception=None):
    """Close DB connection stored in g."""
    db = g.pop("db", None)
    if db is not None:
        db.close()
