import sys
import os
import importlib
import pytest

# Ensure project root AND tests dir are on sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

# Set env BEFORE importing config/app
os.environ["ADMIN_API_KEY"] = "sk-test-admin"
os.environ["UPSTREAM_API_KEY"] = "test-upstream-key"
os.environ["KEY_PREFIX"] = "sk-test"


@pytest.fixture
def app(tmp_path):
    """Create test app with temporary database."""
    db_path = str(tmp_path / "test.db")
    os.environ["DB_PATH"] = db_path

    # Reload config & db so DB_PATH takes effect
    import config as _config
    importlib.reload(_config)
    import db.database as _dbmod
    importlib.reload(_dbmod)
    import auth.api_keys as _ak
    importlib.reload(_ak)
    import auth.middleware as _mw
    importlib.reload(_mw)
    import endpoints.admin as _admin
    importlib.reload(_admin)
    import endpoints.chat as _chat
    importlib.reload(_chat)
    import endpoints.responses as _resp
    importlib.reload(_resp)
    import endpoints.models as _models
    importlib.reload(_models)
    import endpoints.health as _health
    importlib.reload(_health)
    import endpoints.usage as _usage
    importlib.reload(_usage)
    import app as _app
    importlib.reload(_app)

    flask_app = _app.create_app()
    flask_app.config["TESTING"] = True
    yield flask_app

    # Cleanup
    if os.path.exists(db_path):
        os.unlink(db_path)
    os.environ.pop("DB_PATH", None)


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def admin_key(app):
    """Create an admin key and return it."""
    from auth.api_keys import create_key
    key = create_key(uses=-1, admin=1)
    return key


@pytest.fixture
def user_key(app):
    """Create a regular user key and return it."""
    from auth.api_keys import create_key
    key = create_key(uses=100, admin=0)
    return key

