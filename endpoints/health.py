from flask import Blueprint, jsonify

health_bp = Blueprint("health", __name__)


@health_bp.route("/health")
@health_bp.route("/v1/health")
def health():
    return jsonify({"status": "ok"})
