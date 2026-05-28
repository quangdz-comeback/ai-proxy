"""Conversion helpers between OpenAI Responses API and Chat Completions formats."""

import json
import logging
import uuid
import time

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Input conversion: Responses API → Chat Completions messages
# ---------------------------------------------------------------------------

def responses_input_to_messages(body):
    """Convert a Responses API request body into a Chat Completions messages list.

    Handles:
    - body["instructions"] → system message (prepended)
    - body["input"] as str  → single user message
    - body["input"] as list → each item converted per its ``type``
    - body["previous_response_id"] → ignored (stateless proxy)
    """
    messages = []

    # Instructions → system message
    instructions = body.get("instructions")
    if instructions:
        messages.append({"role": "system", "content": instructions})

    raw_input = body.get("input", "")

    if isinstance(raw_input, str):
        # Simple string input → single user message
        messages.append({"role": "user", "content": raw_input})
    elif isinstance(raw_input, list):
        for item in raw_input:
            msg = _convert_input_item(item)
            if msg is not None:
                messages.append(msg)
    # else: no input → leave messages empty (upstream will error if needed)

    return messages


def _convert_input_item(item):
    """Convert a single Responses API input item to a CC message dict."""
    item_type = item.get("type")

    # If no type but has role, treat as message
    if item_type is None and "role" in item:
        item_type = "message"

    if item_type == "message":
        role = item.get("role", "user")
        content = item.get("content")

        # Content can be a string or an array of parts
        if isinstance(content, list):
            # Concatenate text from input_text parts
            parts = []
            for part in content:
                if isinstance(part, dict) and part.get("type") == "input_text":
                    parts.append(part.get("text", ""))
                elif isinstance(part, str):
                    parts.append(part)
                else:
                    # Fallback: try to extract text
                    parts.append(part.get("text", str(part)) if isinstance(part, dict) else str(part))
            content = "".join(parts)

        return {"role": role, "content": content or ""}

    elif item_type == "function_call":
        tc_id = item.get("call_id") or item.get("id") or f"call_{uuid.uuid4().hex[:8]}"
        name = item.get("name", "")
        arguments = item.get("arguments", "{}")
        return {
            "role": "assistant",
            "tool_calls": [{
                "id": tc_id,
                "type": "function",
                "function": {
                    "name": name,
                    "arguments": arguments,
                },
            }],
        }

    elif item_type == "function_call_output":
        call_id = item.get("call_id", "")
        output = item.get("output", "")
        return {
            "role": "tool",
            "tool_call_id": call_id,
            "content": output,
        }

    # Unknown type → skip
    return None


# ---------------------------------------------------------------------------
# Tool conversion
# ---------------------------------------------------------------------------

def responses_tools_to_cc_tools(tools):
    """Convert Responses API tools → Chat Completions tools format.

    Input:  [{"type": "function", "name": "...", "parameters": {...}, "description": "..."}]
    Output: [{"type": "function", "function": {"name": "...", "parameters": {...}, "description": "..."}}]
    """
    if not tools:
        return []

    cc_tools = []
    for tool in tools:
        if tool.get("type") == "function":
            cc_tools.append({
                "type": "function",
                "function": {
                    "name": tool.get("name", ""),
                    "parameters": tool.get("parameters", {}),
                    "description": tool.get("description", ""),
                },
            })
    return cc_tools


# ---------------------------------------------------------------------------
# Non-streaming response conversion: CC → Responses API
# ---------------------------------------------------------------------------

def build_response_object(chat_response, resp_id, created_at):
    """Convert a non-streaming Chat Completions response to Responses API format."""
    model = chat_response.get("model", "")
    choices = chat_response.get("choices", [])
    usage_raw = chat_response.get("usage", {})

    status = "completed"
    output_items = []

    if choices:
        choice = choices[0]
        finish_reason = choice.get("finish_reason", "")
        if finish_reason == "length":
            status = "incomplete"

        message = choice.get("message", {})

        # Text content → message output item
        content = message.get("content")
        if content:
            msg_id = f"msg_{uuid.uuid4().hex[:24]}"
            output_items.append({
                "type": "message",
                "id": msg_id,
                "role": "assistant",
                "content": [{
                    "type": "output_text",
                    "text": content,
                    "annotations": [],
                }],
            })

        # Tool calls → function_call output items
        tool_calls = message.get("tool_calls")
        if tool_calls:
            for tc in tool_calls:
                tc_id = tc.get("id", f"call_{uuid.uuid4().hex[:8]}")
                output_items.append({
                    "type": "function_call",
                    "id": tc_id,
                    "call_id": tc_id,
                    "name": tc.get("function", {}).get("name", ""),
                    "arguments": tc.get("function", {}).get("arguments", ""),
                })

    return {
        "id": resp_id,
        "object": "response",
        "created_at": created_at,
        "model": model,
        "status": status,
        "output": output_items,
        "usage": {
            "input_tokens": usage_raw.get("prompt_tokens", 0),
            "output_tokens": usage_raw.get("completion_tokens", 0),
            "total_tokens": usage_raw.get("total_tokens", 0),
        },
    }


# ---------------------------------------------------------------------------
# Streaming response conversion: CC chunks → Responses API events
# ---------------------------------------------------------------------------

class ResponseStreamConverter:
    """Stateful converter from Chat Completions SSE chunks to Responses API events.

    Maintains accumulators for text and tool calls across chunks so that the
    ``done`` events carry the full accumulated values.
    """

    def __init__(self, resp_id, model, created_at):
        self.resp_id = resp_id
        self.model = model
        self.created_at = created_at

        self.started = False
        self.text_started = False
        self.text_accumulator = ""
        self.tool_calls_accumulator = {}  # index → {id, call_id, name, arguments, output_index}
        self.output_index = 0
        self.current_text_output_index = 0
        self.usage = None

    # -- public API ----------------------------------------------------------

    def convert_chunk(self, chunk):
        """Convert a single CC streaming chunk to a list of Responses API events.

        Returns a (possibly empty) list of event dicts.
        """
        events = []
        choices = chunk.get("choices", [])

        if not choices:
            # Some providers send a final chunk with only usage info
            if chunk.get("usage"):
                self.usage = chunk["usage"]
            return events

        choice = choices[0]
        delta = choice.get("delta", {})

        # ---- First chunk (role present) ----
        if not self.started and delta.get("role"):
            self.started = True
            events.append(self._created_event())
            events.append(self._in_progress_event())

        # ---- Text content delta ----
        if delta.get("content"):
            if not self.text_started:
                self.text_started = True
                self.current_text_output_index = self.output_index
                self.output_index += 1
            self.text_accumulator += delta["content"]
            events.append({
                "type": "response.output_text.delta",
                "output_index": self.current_text_output_index,
                "content_index": 0,
                "delta": delta["content"],
            })

        # ---- Tool call deltas ----
        if delta.get("tool_calls"):
            for tc_delta in delta["tool_calls"]:
                idx = tc_delta.get("index", 0)

                if idx not in self.tool_calls_accumulator:
                    # New tool call starting
                    tc_id = tc_delta.get("id", f"call_{idx}_{uuid.uuid4().hex[:8]}")
                    name = tc_delta.get("function", {}).get("name", "")
                    self.tool_calls_accumulator[idx] = {
                        "id": tc_id,
                        "call_id": tc_id,
                        "name": name,
                        "arguments": "",
                        "output_index": self.output_index,
                    }
                    self.output_index += 1

                    events.append({
                        "type": "response.output_item.added",
                        "output_index": self.tool_calls_accumulator[idx]["output_index"],
                        "item": {
                            "type": "function_call",
                            "id": tc_id,
                            "call_id": tc_id,
                            "name": name,
                            "arguments": "",
                        },
                    })

                acc = self.tool_calls_accumulator[idx]
                args_delta = tc_delta.get("function", {}).get("arguments", "")
                if args_delta:
                    acc["arguments"] += args_delta
                    events.append({
                        "type": "response.function_call_arguments.delta",
                        "output_index": acc["output_index"],
                        "item_id": acc["id"],
                        "call_id": acc["call_id"],
                        "delta": args_delta,
                    })

        # ---- Finish ----
        if choice.get("finish_reason"):
            # Text done
            if self.text_accumulator:
                events.append({
                    "type": "response.output_text.done",
                    "output_index": self.current_text_output_index,
                    "content_index": 0,
                    "text": self.text_accumulator,
                })

            # Tool call arguments done
            for idx in sorted(self.tool_calls_accumulator.keys()):
                acc = self.tool_calls_accumulator[idx]
                events.append({
                    "type": "response.function_call_arguments.done",
                    "output_index": acc["output_index"],
                    "item_id": acc["id"],
                    "call_id": acc["call_id"],
                    "arguments": acc["arguments"],
                })

            events.append(self._completed_event(choice["finish_reason"]))

        return events

    # -- private helpers -----------------------------------------------------

    def _base_response(self, status="in_progress", output=None):
        """Build the response sub-object shared by created / in_progress / completed."""
        if output is None:
            output = []
        return {
            "id": self.resp_id,
            "object": "response",
            "created_at": self.created_at,
            "model": self.model,
            "status": status,
            "output": output,
        }

    def _created_event(self):
        return {
            "type": "response.created",
            "response": self._base_response(status="in_progress"),
        }

    def _in_progress_event(self):
        return {
            "type": "response.in_progress",
            "response": self._base_response(status="in_progress"),
        }

    def _completed_event(self, finish_reason):
        """Build the final response.completed event with full output and usage."""
        output_items = []

        # Text output item
        if self.text_accumulator:
            msg_id = f"msg_{uuid.uuid4().hex[:24]}"
            output_items.append({
                "type": "message",
                "id": msg_id,
                "role": "assistant",
                "content": [{
                    "type": "output_text",
                    "text": self.text_accumulator,
                    "annotations": [],
                }],
            })

        # Tool call output items
        for idx in sorted(self.tool_calls_accumulator.keys()):
            acc = self.tool_calls_accumulator[idx]
            output_items.append({
                "type": "function_call",
                "id": acc["id"],
                "call_id": acc["call_id"],
                "name": acc["name"],
                "arguments": acc["arguments"],
            })

        status = "incomplete" if finish_reason == "length" else "completed"
        resp_obj = self._base_response(status=status, output=output_items)

        # Attach usage
        if self.usage:
            resp_obj["usage"] = {
                "input_tokens": self.usage.get("prompt_tokens", 0),
                "output_tokens": self.usage.get("completion_tokens", 0),
                "total_tokens": self.usage.get("total_tokens", 0),
            }

        return {
            "type": "response.completed",
            "response": resp_obj,
        }
