import time
import logging
from flask import g, request, jsonify
from auth.api_keys import get_key, decrement_uses, log_request

logger = logging.getLogger(__name__)


def init_auth(app):
    """Register before_request and after_request hooks for auth & logging."""

    @app.before_request
    def before_request():
        # Skip auth for health, models list, and OPTIONS preflight
        if request.path in ("/health", "/v1/health", "/v1/models"):
            g.api_key = None
            g.is_admin = False
            g.start_time = time.time()
            return None
        if request.method == "OPTIONS":
            g.api_key = None
            g.is_admin = False
            g.start_time = time.time()
            return None

        # Parse Authorization header
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return jsonify({"error": {"message": "Missing API key"}}), 401
        key = auth_header[7:].strip()
        if not key:
            return jsonify({"error": {"message": "Missing API key"}}), 401

        # Bootstrap admin key from config
        from config import ADMIN_API_KEY
        if ADMIN_API_KEY and key == ADMIN_API_KEY:
            g.api_key = key
            g.is_admin = True
            g.start_time = time.time()
            return None

        # Validate key
        key_row = get_key(key)
        if key_row is None:
            return jsonify({"error": {"message": "Invalid API key"}}), 401

        # Check quota
        if key_row["uses"] == 0:
            return jsonify({"error": {"message": "Quota exceeded"}}), 429

        # Skip quota-decrement for status & admin routes
        if not (request.path == "/v1/status" or request.path.startswith("/v1/admin/")):
            decrement_uses(key)

        g.api_key = key
        g.is_admin = bool(key_row["admin"])
        g.start_time = time.time()
        return None

    @app.after_request
    def after_request(response):
        if not hasattr(g, "api_key") or g.api_key is None:
            return response

        latency_ms = int((time.time() - g.start_time) * 1000)

        # Try to extract model from request body
        model = ""
        try:
            body = request.get_json(silent=True)
            if body and "model" in body:
                model = body["model"]
        except Exception:
            pass

        stream = 0
        try:
            body = request.get_json(silent=True)
            if body and body.get("stream"):
                stream = 1
        except Exception:
            pass

        error = None
        if response.status_code >= 400:
            try:
                data = response.get_json(silent=True)
                if data and "error" in data:
                    err_obj = data["error"]
                    if isinstance(err_obj, dict):
                        error = err_obj.get("message", str(err_obj))
                    else:
                        error = str(err_obj)
            except Exception:
                error = response.get_data(as_text=True)[:500]

        try:
            log_request(
                api_key=g.api_key,
                endpoint=request.path,
                model=model,
                stream=stream,
                status=response.status_code,
                latency_ms=latency_ms,
                error=error,
            )
        except Exception as e:
            logger.error(f"Failed to log request: {e}")

        return response
