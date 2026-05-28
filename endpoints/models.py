from flask import Blueprint, jsonify

from models.registry import get_model_list

models_bp = Blueprint("models", __name__)


@models_bp.route("/v1/models", methods=["GET"])
def list_models():
    """Return available models from the registry."""
    return jsonify({"object": "list", "data": get_model_list()}), 200
