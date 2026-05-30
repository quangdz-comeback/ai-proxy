import logging
import time

from flask import Blueprint, request, jsonify, g

from models.registry import resolve_model
from upstream.client import call_upstream, iter_sse_lines
from upstream.errors import UpstreamError
from format.sse import sse_response
from budget.pipeline import transform_payload
from budget.trigger import is_budget_mode

logger = logging.getLogger(__name__)

chat_bp = Blueprint("chat", __name__)


@chat_bp.route("/v1/chat/completions", methods=["POST"])
def chat_completions():
    """Proxy chat completion requests to upstream."""
    try:
        body = request.get_json(force=True, silent=True)
        if body is None:
            return jsonify({"error": {"message": "Invalid JSON body", "type": "invalid_request_error"}}), 400

        if "model" not in body:
            return jsonify({"error": {"message": "'model' is required", "type": "invalid_request_error"}}), 400

        if "messages" not in body:
            return jsonify({"error": {"message": "'messages' is required", "type": "invalid_request_error"}}), 400

        # Resolve model alias to actual model name
        try:
            resolved = resolve_model(body["model"])
        except ValueError as e:
            return jsonify({"error": {"message": str(e), "type": "invalid_request_error"}}), 400

        body["model"] = resolved

        # Apply budget compression if triggered
        if is_budget_mode(body):
            body = transform_payload(body, g.api_key or "")

        stream = body.get("stream", False)

        if stream:
            return _handle_streaming(body)
        else:
            return _handle_non_streaming(body)

    except UpstreamError:
        raise
    except Exception as e:
        logger.exception("Unexpected error in chat_completions")
        return jsonify({"error": {"message": "Internal server error", "type": "internal_error"}}), 500


def _handle_non_streaming(payload):
    """Handle non-streaming chat completion request."""
    try:
        result = call_upstream(payload, stream=False)
        return jsonify(result), 200
    except UpstreamError:
        raise
    except Exception as e:
        logger.exception("Error in non-streaming upstream call")
        return jsonify({"error": {"message": "Internal server error", "type": "internal_error"}}), 500


def _handle_streaming(payload):
    """Handle streaming chat completion request."""
    try:
        resp = call_upstream(payload, stream=True)
    except UpstreamError:
        raise
    except Exception as e:
        logger.exception("Error initiating streaming upstream call")
        return jsonify({"error": {"message": "Internal server error", "type": "internal_error"}}), 500

    def generate():
        try:
            for line in iter_sse_lines(resp):
                if not line:
                    # Skip empty lines (SSE keep-alive)
                    continue
                if line.startswith("data: "):
                    yield f"{line}\n\n"
                    if line == "data: [DONE]":
                        return
                else:
                    # Forward other lines as-is
                    yield f"{line}\n\n"
        except Exception as e:
            logger.exception("Error during stream iteration")
            yield f"data: {{\"error\": \"Stream interrupted\"}}\n\n"
        finally:
            try:
                resp.close()
            except Exception:
                pass

    return sse_response(generate())
