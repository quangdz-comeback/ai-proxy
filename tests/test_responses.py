"""Tests for /v1/responses endpoint and format conversion helpers."""
import json
from unittest.mock import patch, MagicMock

from helpers import make_mock_response
from format.responses_api import (
    responses_input_to_messages,
    responses_tools_to_cc_tools,
)


class TestResponsesInputConversion:
    """Test Responses API input → Chat Completions messages conversion."""

    def test_string_input(self):
        """String input becomes a single user message."""
        body = {"input": "Hello, world!"}
        messages = responses_input_to_messages(body)
        assert len(messages) == 1
        assert messages[0]["role"] == "user"
        # Content may be string or list of parts
        content = messages[0]["content"]
        if isinstance(content, str):
            assert content == "Hello, world!"
        else:
            # Array of parts form
            assert any(
                (isinstance(p, dict) and p.get("text") == "Hello, world!")
                or p == "Hello, world!"
                for p in content
            )

    def test_array_input_with_messages(self):
        """Array input with role messages → messages list."""
        body = {
            "input": [
                {"role": "user", "content": "What's the weather?"},
                {"role": "assistant", "content": "It's sunny."},
                {"role": "user", "content": "Where?"},
            ]
        }
        messages = responses_input_to_messages(body)
        assert len(messages) == 3
        assert messages[0]["role"] == "user"
        assert messages[1]["role"] == "assistant"
        assert messages[2]["role"] == "user"

    def test_instructions_become_system_message(self):
        """instructions parameter is prepended as a system message."""
        body = {
            "input": "Hello",
            "instructions": "You are a helpful assistant.",
        }
        messages = responses_input_to_messages(body)
        assert len(messages) >= 2
        assert messages[0]["role"] == "system"
        content = messages[0]["content"]
        if isinstance(content, str):
            assert content == "You are a helpful assistant."
        else:
            # part-array form
            joined = "".join(
                p.get("text", "") if isinstance(p, dict) else str(p)
                for p in content
            )
            assert "helpful assistant" in joined

    def test_content_as_array_of_parts(self):
        """Content can be array of parts with type input_text."""
        body = {
            "input": [
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": "Part one. "},
                        {"type": "input_text", "text": "Part two."},
                    ],
                }
            ]
        }
        messages = responses_input_to_messages(body)
        assert len(messages) == 1
        assert messages[0]["role"] == "user"
        content = messages[0]["content"]
        # Combined text should include both parts
        if isinstance(content, str):
            assert "Part one." in content
            assert "Part two." in content
        else:
            joined = "".join(
                p.get("text", "") if isinstance(p, dict) else str(p)
                for p in content
            )
            assert "Part one." in joined
            assert "Part two." in joined


class TestResponsesToolsConversion:
    """Test Responses API tools → Chat Completions tools conversion."""

    def test_function_tool_conversion(self):
        """Responses function tool → CC nested function format."""
        tools = [
            {
                "type": "function",
                "name": "get_weather",
                "description": "Get the current weather",
                "parameters": {
                    "type": "object",
                    "properties": {"location": {"type": "string"}},
                    "required": ["location"],
                },
            }
        ]
        cc_tools = responses_tools_to_cc_tools(tools)
        assert len(cc_tools) == 1
        assert cc_tools[0]["type"] == "function"
        # CC format nests under "function"
        assert "function" in cc_tools[0]
        fn = cc_tools[0]["function"]
        assert fn["name"] == "get_weather"
        assert fn["description"] == "Get the current weather"
        assert fn["parameters"]["properties"]["location"]["type"] == "string"

    def test_empty_tools(self):
        """Empty/None tools returns empty list."""
        assert responses_tools_to_cc_tools([]) == []
        assert responses_tools_to_cc_tools(None) in ([], None)

    def test_multiple_tools(self):
        """Multiple tools all get converted."""
        tools = [
            {"type": "function", "name": "f1", "parameters": {"type": "object"}},
            {"type": "function", "name": "f2", "parameters": {"type": "object"}},
        ]
        cc_tools = responses_tools_to_cc_tools(tools)
        assert len(cc_tools) == 2
        names = [t["function"]["name"] for t in cc_tools]
        assert "f1" in names
        assert "f2" in names


class TestResponsesEndpointNonStreaming:
    """Test /v1/responses non-streaming flow."""

    @patch("upstream.client.requests.post")
    def test_string_input_conversion(self, mock_post, client, user_key):
        """Responses endpoint with string input."""
        upstream_resp = {
            "id": "chatcmpl-xyz",
            "object": "chat.completion",
            "created": 1700000000,
            "model": "mimo-v2.5-pro",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "Hi there!"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
        }
        mock_post.return_value = make_mock_response(200, json_body=upstream_resp)

        r = client.post(
            "/v1/responses",
            headers={"Authorization": f"Bearer {user_key}"},
            json={
                "model": "mimo-v2.5-pro",
                "input": "Hello",
            },
        )
        assert r.status_code == 200
        data = r.get_json()
        # Response object has output array
        assert "output" in data
        assert isinstance(data["output"], list)

        # Confirm payload sent to upstream is converted
        call_kwargs = mock_post.call_args
        payload = call_kwargs.kwargs.get("json", call_kwargs[1].get("json", {}))
        assert payload["model"] == "mimo-v2.5-pro"
        assert "messages" in payload
        assert len(payload["messages"]) == 1
        assert payload["messages"][0]["role"] == "user"

    @patch("upstream.client.requests.post")
    def test_instructions_to_system_message(self, mock_post, client, user_key):
        """instructions parameter is converted to system message."""
        upstream_resp = {
            "id": "chatcmpl-test",
            "object": "chat.completion",
            "created": 1700000000,
            "model": "mimo-v2.5",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "OK"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 5, "completion_tokens": 1, "total_tokens": 6},
        }
        mock_post.return_value = make_mock_response(200, json_body=upstream_resp)

        client.post(
            "/v1/responses",
            headers={"Authorization": f"Bearer {user_key}"},
            json={
                "model": "mimo-v2.5",
                "input": "Hello",
                "instructions": "Be terse.",
            },
        )

        call_kwargs = mock_post.call_args
        payload = call_kwargs.kwargs.get("json", call_kwargs[1].get("json", {}))
        msgs = payload["messages"]
        assert msgs[0]["role"] == "system"

    @patch("upstream.client.requests.post")
    def test_array_input_with_messages(self, mock_post, client, user_key):
        """Array input with history is forwarded."""
        upstream_resp = {
            "id": "chatcmpl-test",
            "object": "chat.completion",
            "created": 1700000000,
            "model": "mimo-v2.5",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "Reply"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 5, "completion_tokens": 1, "total_tokens": 6},
        }
        mock_post.return_value = make_mock_response(200, json_body=upstream_resp)

        client.post(
            "/v1/responses",
            headers={"Authorization": f"Bearer {user_key}"},
            json={
                "model": "mimo-v2.5",
                "input": [
                    {"role": "user", "content": "Question 1"},
                    {"role": "assistant", "content": "Answer 1"},
                    {"role": "user", "content": "Question 2"},
                ],
            },
        )

        call_kwargs = mock_post.call_args
        payload = call_kwargs.kwargs.get("json", call_kwargs[1].get("json", {}))
        assert len(payload["messages"]) == 3

    @patch("upstream.client.requests.post")
    def test_tools_converted_to_cc_format(self, mock_post, client, user_key):
        """Responses-format tools are converted to CC format for upstream."""
        upstream_resp = {
            "id": "chatcmpl-test",
            "object": "chat.completion",
            "created": 1700000000,
            "model": "mimo-v2.5",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "OK"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 5, "completion_tokens": 1, "total_tokens": 6},
        }
        mock_post.return_value = make_mock_response(200, json_body=upstream_resp)

        client.post(
            "/v1/responses",
            headers={"Authorization": f"Bearer {user_key}"},
            json={
                "model": "mimo-v2.5",
                "input": "Hi",
                "tools": [
                    {
                        "type": "function",
                        "name": "my_tool",
                        "parameters": {"type": "object"},
                    }
                ],
            },
        )

        call_kwargs = mock_post.call_args
        payload = call_kwargs.kwargs.get("json", call_kwargs[1].get("json", {}))
        assert "tools" in payload
        # CC format nests under "function"
        assert payload["tools"][0]["type"] == "function"
        assert "function" in payload["tools"][0]
        assert payload["tools"][0]["function"]["name"] == "my_tool"

    @patch("upstream.client.requests.post")
    def test_content_array_parts(self, mock_post, client, user_key):
        """Content array of input_text parts is supported."""
        upstream_resp = {
            "id": "chatcmpl-test",
            "object": "chat.completion",
            "created": 1700000000,
            "model": "mimo-v2.5",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "OK"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 5, "completion_tokens": 1, "total_tokens": 6},
        }
        mock_post.return_value = make_mock_response(200, json_body=upstream_resp)

        r = client.post(
            "/v1/responses",
            headers={"Authorization": f"Bearer {user_key}"},
            json={
                "model": "mimo-v2.5",
                "input": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "input_text", "text": "Hello "},
                            {"type": "input_text", "text": "world"},
                        ],
                    }
                ],
            },
        )
        assert r.status_code == 200


class TestResponsesEndpointStreaming:
    """Test /v1/responses streaming flow."""

    @patch("upstream.client.requests.post")
    def test_streaming_produces_response_events(self, mock_post, client, user_key):
        """Streaming /v1/responses returns SSE events in Responses format."""
        # Build upstream CC stream chunks
        cc_chunks = [
            {
                "id": "chatcmpl-stream",
                "object": "chat.completion.chunk",
                "created": 1700000000,
                "model": "mimo-v2.5",
                "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}],
            },
            {
                "id": "chatcmpl-stream",
                "object": "chat.completion.chunk",
                "created": 1700000000,
                "model": "mimo-v2.5",
                "choices": [{"index": 0, "delta": {"content": "Hi"}, "finish_reason": None}],
            },
            {
                "id": "chatcmpl-stream",
                "object": "chat.completion.chunk",
                "created": 1700000000,
                "model": "mimo-v2.5",
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
            },
        ]
        sse_lines = [f"data: {json.dumps(c)}" for c in cc_chunks] + ["data: [DONE]"]

        mock_post.return_value = make_mock_response(200, iter_lines_data=sse_lines)

        r = client.post(
            "/v1/responses",
            headers={"Authorization": f"Bearer {user_key}"},
            json={
                "model": "mimo-v2.5",
                "input": "Hi",
                "stream": True,
            },
        )
        assert r.status_code == 200
        assert r.content_type.startswith("text/event-stream")

        body = r.get_data(as_text=True)
        # Responses API uses event-named SSE events
        # Check for at least one of the known Responses event types
        responses_events = [
            "response.created",
            "response.in_progress",
            "response.output_text.delta",
            "response.completed",
            "response.output_item",
        ]
        assert any(ev in body for ev in responses_events), (
            f"No Responses API event types found in stream body. Body sample: {body[:500]}"
        )
