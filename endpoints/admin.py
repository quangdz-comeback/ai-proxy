import logging

from flask import Blueprint, request, jsonify, g

from config import ADMIN_API_KEY
from db.database import get_db
from auth.api_keys import create_key, list_keys, edit_key, delete_key

logger = logging.getLogger(__name__)

admin_bp = Blueprint("admin", __name__)


def _require_admin():
    """Check if the current user is an admin. Returns error response or None."""
    if g.is_admin == 1:
        return None
    if g.api_key == ADMIN_API_KEY:
        return None
    return jsonify({"error": {"message": "Admin access required", "type": "permission_error"}}), 403


@admin_bp.route("/v1/status", methods=["GET"])
def status():
    """Return info about the current API key. Any authenticated user can access."""
    from auth.api_keys import get_key

    key = g.api_key
    row = get_key(key)
    if row is None:
        return jsonify({"error": {"message": "Key not found", "type": "invalid_request_error"}}), 404

    return jsonify({
        "key": row["key"],
        "uses": row["uses"],
        "admin": row["admin"],
    }), 200


@admin_bp.route("/v1/admin/api/create", methods=["POST"])
def admin_create_key():
    """Create a new API key."""
    err = _require_admin()
    if err:
        return err

    body = request.get_json(force=True, silent=True) or {}

    uses = body.get("uses", -1)
    admin = body.get("admin", 0)

    try:
        key = create_key(uses=uses, admin=admin)
    except Exception as e:
        logger.exception("Error creating key")
        return jsonify({"error": {"message": str(e), "type": "server_error"}}), 500

    return jsonify({"key": key}), 200


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


@admin_bp.route("/v1/admin/api/edit", methods=["POST"])
def admin_edit_key():
    """Edit an existing API key."""
    err = _require_admin()
    if err:
        return err

    body = request.get_json(force=True, silent=True)
    if body is None:
        return jsonify({"error": {"message": "Invalid JSON body", "type": "invalid_request_error"}}), 400

    key = body.get("key")
    if not key:
        return jsonify({"error": {"message": "'key' is required", "type": "invalid_request_error"}}), 400

    uses = body.get("uses")
    admin = body.get("admin")

    try:
        edit_key(key, uses=uses, admin=admin)
    except Exception as e:
        logger.exception("Error editing key")
        return jsonify({"error": {"message": str(e), "type": "server_error"}}), 500

    return jsonify({"status": "ok"}), 200


@admin_bp.route("/v1/admin/api/delete", methods=["POST"])
def admin_delete_key():
    """Delete an API key."""
    err = _require_admin()
    if err:
        return err

    body = request.get_json(force=True, silent=True)
    if body is None:
        return jsonify({"error": {"message": "Invalid JSON body", "type": "invalid_request_error"}}), 400

    key = body.get("key")
    if not key:
        return jsonify({"error": {"message": "'key' is required", "type": "invalid_request_error"}}), 400

    try:
        delete_key(key)
    except Exception as e:
        logger.exception("Error deleting key")
        return jsonify({"error": {"message": str(e), "type": "server_error"}}), 500

    return jsonify({"status": "ok"}), 200


@admin_bp.route("/v1/admin/logs", methods=["GET"])
def admin_logs():
    """Return the last 100 request log entries."""
    err = _require_admin()
    if err:
        return err

    try:
        conn = get_db()
        rows = conn.execute(
            "SELECT * FROM request_log ORDER BY created_at DESC LIMIT 100"
        ).fetchall()
        conn.close()

        logs = [dict(row) for row in rows]
    except Exception as e:
        logger.exception("Error fetching logs")
        return jsonify({"error": {"message": str(e), "type": "server_error"}}), 500

    return jsonify({"logs": logs}), 200
