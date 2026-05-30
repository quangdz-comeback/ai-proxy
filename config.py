import os
from dotenv import load_dotenv

load_dotenv()

UPSTREAM_URL = os.getenv("UPSTREAM_URL", "http://localhost:11434/v1/chat/completions")
UPSTREAM_API_KEY = os.getenv("UPSTREAM_API_KEY", "")
GUEST_API_KEY = "guest"
ADMIN_API_KEY = os.getenv("ADMIN_API_KEY", "")  # MUST be set in production
KEY_PREFIX = os.getenv("KEY_PREFIX", "sk-proxy")
DB_PATH = os.getenv("DB_PATH", "api_keys.db")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
PORT = int(os.getenv("PORT", "80"))


def get_upstream_auth() -> str:
    """Return Bearer token for upstream. Falls back to 'guest' if no key configured."""
    return UPSTREAM_API_KEY if UPSTREAM_API_KEY else GUEST_API_KEY

# Budget mode configuration
BUDGET_ENABLED = os.getenv("BUDGET_ENABLED", "true").lower() == "true"
BUDGET_CACHE_SIZE = int(os.getenv("BUDGET_CACHE_SIZE", "256"))
BUDGET_CACHE_TTL = int(os.getenv("BUDGET_CACHE_TTL", "3600"))
BUDGET_HISTORY_KEEP_N = int(os.getenv("BUDGET_HISTORY_KEEP_N", "4"))
BUDGET_COMPRESS_THRESHOLD = int(os.getenv("BUDGET_COMPRESS_THRESHOLD", "500"))
