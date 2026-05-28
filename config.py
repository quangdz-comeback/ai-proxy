import os
from dotenv import load_dotenv

load_dotenv()

UPSTREAM_URL = os.getenv("UPSTREAM_URL", "https://opengateway.gitlawb.com/v1/chat/completions")
UPSTREAM_API_KEY = os.getenv("UPSTREAM_API_KEY", "")
GUEST_API_KEY = "guest"
ADMIN_API_KEY = os.getenv("ADMIN_API_KEY", "sk-quangdz-admin-ai")
KEY_PREFIX = os.getenv("KEY_PREFIX", "sk-quangdz")
DB_PATH = os.getenv("DB_PATH", "api_keys.db")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")


def get_upstream_auth() -> str:
    """Return Bearer token for upstream. Falls back to 'guest' if no key configured."""
    return UPSTREAM_API_KEY if UPSTREAM_API_KEY else GUEST_API_KEY
