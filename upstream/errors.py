import gzip
import json
import logging

logger = logging.getLogger(__name__)

_GZIP_MAGIC = b'\x1f\x8b'


def _safe_read_resp(resp):
    """Read response body safely, handling mismatched gzip encoding."""
    try:
        raw = resp.raw.read()
        resp.raw._fp = None
    except Exception:
        return b''

    content_encoding = resp.headers.get('Content-Encoding', '').lower()
    if content_encoding == 'gzip' and raw[:2] == _GZIP_MAGIC:
        try:
            raw = gzip.decompress(raw)
        except Exception:
            pass

    return raw


class UpstreamError(Exception):
    def __init__(self, message, status_code=502):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


class RateLimitError(UpstreamError):
    """429 - Rate limited by upstream."""
    def __init__(self, message="Rate limited by upstream"):
        super().__init__(message, 429)


class AuthError(UpstreamError):
    """401/403 - Upstream authentication failed."""
    def __init__(self, message="Upstream authentication failed"):
        super().__init__(message, 401)


class ModelNotFoundError(UpstreamError):
    """404 - Model not found."""
    def __init__(self, message="Model not found"):
        super().__init__(message, 404)


class ServerError(UpstreamError):
    """5xx - Upstream server error."""
    def __init__(self, message="Upstream server error"):
        super().__init__(message, 502)


def classify_error(resp):
    """Classify upstream HTTP error response and RAISE appropriate exception."""
    raise _classify(resp)


def _classify(resp):
    """Classify upstream HTTP error response into appropriate exception."""
    status = resp.status_code
    try:
        raw = _safe_read_resp(resp)
        body = json.loads(raw) if raw else {}
        err = body.get("error", {})
        if isinstance(err, dict):
            msg = err.get("message", raw.decode('utf-8', errors='replace') if raw else f"HTTP {status}")
        else:
            msg = str(err)
    except Exception:
        try:
            raw = _safe_read_resp(resp)
            msg = raw.decode('utf-8', errors='replace') if raw else f"HTTP {status}"
        except Exception:
            msg = f"HTTP {status}"

    if status == 429:
        return RateLimitError(msg)
    elif status in (401, 403):
        return AuthError(msg)
    elif status == 404:
        return ModelNotFoundError(msg)
    elif status >= 500:
        return ServerError(msg)
    else:
        return UpstreamError(msg, status)
