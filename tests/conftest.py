import sys
import os
import pytest

# Ensure project root is on sys.path so imports work
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import create_app


@pytest.fixture
def app():
    """Create test app with a temp DB."""
    # Use a temp file for DB so tests don't clobber real data
    import tempfile
    db_fd, db_path = tempfile.mkstemp(suffix=".db")
    os.environ["DB_PATH"] = db_path

    app = create_app()
    app.config["TESTING"] = True
    yield app

    os.close(db_fd)
    os.unlink(db_path)
    # Restore default
    os.environ.pop("DB_PATH", None)


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def admin_headers():
    from config import ADMIN_API_KEY
    return {"Authorization": f"Bearer {ADMIN_API_KEY}"}
