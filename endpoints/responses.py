import json
import logging
import time
import uuid

from flask import Blueprint, request, jsonify, g

from models.registry import resolve_model
from upstream.client import call_upstream, iter_sse_lines
from upstream.errors import UpstreamError
from format.sse import sse_response
from format.responses_api import (
    responses_input_to_messages,
    responses_tools_to_cc_tools,
    build_response_object,
    ResponseStreamConverter,
)
from budget.pipeline import transform_payload
from budget.trigger import is_budget_mode

logger = logging.getLogger(__name__)

responses_bp = Blueprint("responses", __name__)


@responses_bp.route("/v1/responses", methods=["POST"])
def responses():
    """Proxy OpenAI Responses API requests by converting to/from Chat Completions."""
    try:
        body = request.get_json(force=True, silent=True)
        if body is None:
            return jsonify({"error": {"message": "Invalid JSON body", "type": "invalid_request_error"}}), 400

        if "model" not in body:
            return jsonify({"error": {"message": "'model' is required", "type": "invalid_request_error"}}), 400

        # Resolve model alias
        try:
            resolved = resolve_model(body.get("model", ""))
        except ValueError as e:
            return jsonify({"error": {"message": str(e), "type": "invalid_request_error"}}), 400

        # Convert input → messages
        messages = responses_input_to_messages(body)

        # Convert tools if present
        cc_tools = responses_tools_to_cc_tools(body.get("tools", []))

        # Build Chat Completions payload
        stream = body.get("stream", False)
        cc_payload = {
            "model": resolved,
            "messages": messages,
            "stream": stream,
        }

        if cc_tools:
            cc_payload["tools"] = cc_tools
        if body.get("tool_choice"):
            cc_payload["tool_choice"] = body["tool_choice"]
        if body.get("temperature") is not None:
            cc_payload["temperature"] = body["temperature"]
        if body.get("top_p") is not None:
            cc_payload["top_p"] = body["top_p"]
        if body.get("max_output_tokens"):
            cc_payload["max_tokens"] = body["max_output_tokens"]
        if body.get("reasoning_effort"):
            cc_payload["reasoning_effort"] = body["reasoning_effort"]

        # Apply budget compression if triggered
        if is_budget_mode(cc_payload):
            cc_payload = transform_payload(cc_payload, g.api_key or "")

        if stream:
            return _handle_streaming(cc_payload, body.get("model", resolved))
        else:
            return _handle_non_streaming(cc_payload, body.get("model", resolved))

    except UpstreamError:
        raise
    except Exception as e:
        logger.exception("Unexpected error in responses endpoint")
        return jsonify({"error": {"message": "Internal server error", "type": "internal_error"}}), 500


def _handle_non_streaming(cc_payload, model_display):
    """Handle non-streaming Responses API request."""
    try:
        result = call_upstream(cc_payload, stream=False)
    except UpstreamError:
        raise
    except Exception as e:
        logger.exception("Error in non-streaming upstream call")
        return jsonify({"error": {"message": "Internal server error", "type": "internal_error"}}), 500

    resp_id = f"resp_{uuid.uuid4().hex[:24]}"
    created_at = int(time.time())

    response_obj = build_response_object(result, resp_id, created_at)
    return jsonify(response_obj), 200


def _handle_streaming(cc_payload, model_display):
    """Handle streaming Responses API request."""
    try:
        resp = call_upstream(cc_payload, stream=True)
    except UpstreamError:
        raise
    except Exception as e:
        logger.exception("Error initiating streaming upstream call")
        return jsonify({"error": {"message": "Internal server error", "type": "internal_error"}}), 500

    resp_id = f"resp_{uuid.uuid4().hex[:24]}"
    created_at = int(time.time())
    converter = ResponseStreamConverter(resp_id, model_display, created_at)

    def generate():
        try:
            for line in iter_sse_lines(resp):
                if not line:
                    continue

                if not line.startswith("data: "):
                    continue

                data = line[len("data: "):]
                if data == "[DONE]":
                    break

                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError:
                    logger.warning("Failed to parse SSE chunk: %s", data[:200])
                    continue

                events = converter.convert_chunk(chunk)
                for event in events:
                    yield f"data: {json.dumps(event)}\n\n"

            # Always send DONE at the end
            yield "data: [DONE]\n\n"
        except Exception as e:
            logger.exception("Error during responses stream iteration")
            yield f'data: {{"error": "Stream interrupted"}}\n\n'
        finally:
            try:
                resp.close()
            except Exception:
                pass

    return sse_response(generate())
