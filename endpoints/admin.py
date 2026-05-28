import logging

from flask import Blueprint, request, jsonify, g

from config import ADMIN_API_KEY
from db.database import get_db
from auth.api_keys import create_key, list_keys, edit_key, delete_key, get_logs

logger = logging.getLogger(__name__)

admin_bp = Blueprint("admin", __name__)


def _require_admin():
    """Check if the current user is an admin. Returns error response or None."""
    if g.is_admin == 1 or g.is_admin is True:
        return None
    if g.api_key == ADMIN_API_KEY:
        return None
    return jsonify({"error": {"message": "Admin access required", "type": "permission_error"}}), 403


def _param(name, default=None):
    """Read a parameter from query string first, then JSON body fallback."""
    val = request.args.get(name)
    if val is not None:
        return val
    body = request.get_json(silent=True)
    if body and name in body:
        return body[name]
    return default


def _parse_bool(val):
    """Parse a boolean from string or native bool."""
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        return val.lower() in ("true", "1", "yes")
    return bool(val)


def _parse_uses(raw):
    """Parse uses value. Returns (uses, error_msg). None means unlimited."""
    if raw is None:
        return None, None
    try:
        v = int(raw)
    except (ValueError, TypeError):
        return None, "uses must be an integer"
    if v < 0:
        return None, None  # negative = unlimited
    return v, None


# ── Status ──────────────────────────────────────────────────────────────

@admin_bp.route("/v1/status", methods=["GET"])
def status():
    """Return info about the current API key. Any authenticated user can access."""
    from auth.api_keys import get_key as _get_key

    key = g.api_key
    row = _get_key(key)
    if row is None:
        return jsonify({"error": {"message": "Key not found", "type": "invalid_request_error"}}), 404

    return jsonify({
        "key": row["key"],
        "name": row.get("name"),
        "uses": row["uses"],
        "admin": row["admin"],
    }), 200


# ── Admin Index ─────────────────────────────────────────────────────────

@admin_bp.route("/v1/admin", methods=["GET"])
def admin_index():
    """Admin panel index listing available endpoints."""
    return jsonify({
        "message": "Admin panel",
        "endpoints": [
            "/v1/admin/api/create",
            "/v1/admin/api/list",
            "/v1/admin/api/edit",
            "/v1/admin/api/delete",
            "/v1/admin/logs",
        ],
    })


# ── Create Key ──────────────────────────────────────────────────────────

@admin_bp.route("/v1/admin/api/create", methods=["POST"])
def admin_create_key():
    """Create a new API key."""
    err = _require_admin()
    if err:
        return err

    is_admin_flag = _parse_bool(_param("admin", False))
    uses_raw = _param("uses")
    name = _param("name")

    # Parse uses
    uses = None  # unlimited
    if uses_raw is not None:
        uses, err = _parse_uses(uses_raw)
        if err:
            return jsonify({"error": err}), 400

    try:
        key = create_key(uses=uses, admin=int(is_admin_flag), name=name)
    except ValueError as e:
        return jsonify({"error": str(e)}), 409
    except Exception as e:
        logger.exception("Error creating key")
        return jsonify({"error": {"message": str(e), "type": "server_error"}}), 500

    # Fetch the created key to return full info
    from auth.api_keys import get_key as _get_key
    row = _get_key(key)
    return jsonify({
        "name": row["name"],
        "key": row["key"],
        "uses": row["uses"],
        "admin": bool(row["admin"]),
        "created_at": row["created_at"],
    }), 201


# ── List Keys ───────────────────────────────────────────────────────────

@admin_bp.route("/v1/admin/api/list", methods=["GET"])
def admin_list_keys():
    """List all API keys."""
    err = _require_admin()
    if err:
        return err

    try:
        keys = list_keys()
    except Exception as e:
        logger.exception("Error listing keys")
        return jsonify({"error": {"message": str(e), "type": "server_error"}}), 500

    return jsonify(keys), 200


# ── Edit Key ────────────────────────────────────────────────────────────

@admin_bp.route("/v1/admin/api/edit", methods=["POST", "PATCH", "PUT"])
def admin_edit_key():
    """Edit an existing API key."""
    err = _require_admin()
    if err:
        return err

    key = _param("key")
    if not key:
        return jsonify({"error": "Provide key to edit (param 'key')"}), 400

    updates = {}

    # name
    new_name = _param("name")
    if new_name is not None:
        updates["name"] = new_name

    # uses
    uses_raw = _param("uses")
    if uses_raw is not None:
        uses, err = _parse_uses(uses_raw)
        if err:
            return jsonify({"error": err}), 400
        updates["uses"] = uses

    # admin
    admin_raw = _param("admin")
    if admin_raw is not None:
        updates["admin"] = int(_parse_bool(admin_raw))

    if not updates:
        return jsonify({"error": "Nothing to update. Provide name, uses, or admin."}), 400

    try:
        result = edit_key(key, **updates)
    except ValueError as e:
        return jsonify({"error": str(e)}), 409
    except Exception as e:
        logger.exception("Error editing key")
        return jsonify({"error": {"message": str(e), "type": "server_error"}}), 500

    if result is None:
        return jsonify({"error": "Key not found"}), 404

    return jsonify({
        "key": result["key"],
        "name": result["name"],
        "uses": result["uses"],
        "admin": bool(result["admin"]),
    })


# ── Delete Key ──────────────────────────────────────────────────────────

@admin_bp.route("/v1/admin/api/delete", methods=["POST", "DELETE"])
def admin_delete_key():
    """Delete an API key by key or name."""
    err = _require_admin()
    if err:
        return err

    key = _param("key")
    name = _param("name")

    if not key and not name:
        return jsonify({"error": "Provide name or key to identify the key"}), 400

    try:
        deleted = delete_key(key=key, name=name)
    except Exception as e:
        logger.exception("Error deleting key")
        return jsonify({"error": {"message": str(e), "type": "server_error"}}), 500

    if deleted is None:
        return jsonify({"error": "Key not found"}), 404

    return jsonify({"deleted": deleted})


# ── Request Logs ────────────────────────────────────────────────────────

@admin_bp.route("/v1/admin/logs", methods=["GET"])
def admin_logs():
    """Return request log entries. Optional ?limit=N&key=XXX filters."""
    err = _require_admin()
    if err:
        return err

    limit = request.args.get("limit", 50, type=int)
    key_filter = request.args.get("key")

    try:
        logs = get_logs(limit=limit, api_key=key_filter)
    except Exception as e:
        logger.exception("Error fetching logs")
        return jsonify({"error": {"message": str(e), "type": "server_error"}}), 500

    return jsonify(logs), 200
