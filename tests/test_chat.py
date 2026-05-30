"""Tests for /v1/chat/completions endpoint with mocked upstream."""
import json
from unittest.mock import patch, MagicMock

from helpers import make_mock_response


def _make_chat_response(content="Hello!", model="mimo-v2.5-pro", finish_reason="stop"):
    """Build a standard Chat Completions response."""
    return {
        "id": "chatcmpl-test123",
        "object": "chat.completion",
        "created": 1700000000,
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": finish_reason,
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }


def _sse_lines(chunks):
    """Build SSE lines from a list of chunk dicts."""
    lines = []
    for chunk in chunks:
        lines.append(f"data: {json.dumps(chunk)}")
    lines.append("data: [DONE]")
    return lines


def _make_stream_chunks(content="Hello!", model="mimo-v2.5-pro"):
    """Build streaming SSE chunks for a response."""
    chunks = []
    # First chunk with role
    chunks.append({
        "id": "chatcmpl-test123",
        "object": "chat.completion.chunk",
        "created": 1700000000,
        "model": model,
        "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}],
    })
    # Content chunks
    for char in content:
        chunks.append({
            "id": "chatcmpl-test123",
            "object": "chat.completion.chunk",
            "created": 1700000000,
            "model": model,
            "choices": [{"index": 0, "delta": {"content": char}, "finish_reason": None}],
        })
    # Final chunk
    chunks.append({
        "id": "chatcmpl-test123",
        "object": "chat.completion.chunk",
        "created": 1700000000,
        "model": model,
        "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
    })
    return chunks


class TestChatCompletionsNonStreaming:
    """Test non-streaming chat completions."""

    @patch("upstream.client.requests.post")
    def test_returns_upstream_response(self, mock_post, client, user_key):
        """Non-streaming request returns upstream response directly."""
        upstream_resp = _make_chat_response("Hello from mimo!")
        mock_post.return_value = make_mock_response(200, json_body=upstream_resp)

        r = client.post(
            "/v1/chat/completions",
            headers={"Authorization": f"Bearer {user_key}"},
            json={
                "model": "mimo-v2.5-pro",
                "messages": [{"role": "user", "content": "Hello"}],
            },
        )
        assert r.status_code == 200
        data = r.get_json()
        assert data["id"] == "chatcmpl-test123"
        assert data["choices"][0]["message"]["content"] == "Hello from mimo!"
        assert data["model"] == "mimo-v2.5-pro"

    @patch("upstream.client.requests.post")
    def test_forwards_model_and_messages(self, mock_post, client, user_key):
        """Request payload includes model and messages."""
        upstream_resp = _make_chat_response()
        mock_post.return_value = make_mock_response(200, json_body=upstream_resp)

        client.post(
            "/v1/chat/completions",
            headers={"Authorization": f"Bearer {user_key}"},
            json={
                "model": "mimo-v2.5",
                "messages": [{"role": "user", "content": "test"}],
            },
        )

        call_kwargs = mock_post.call_args
        payload = call_kwargs.kwargs.get("json", call_kwargs[1].get("json", {}))
        assert payload["model"] == "mimo-v2.5"
        assert len(payload["messages"]) == 1


class TestChatCompletionsStreaming:
    """Test streaming chat completions."""

    @patch("upstream.client.requests.post")
    def test_returns_sse_lines(self, mock_post, client, user_key):
        """Streaming request returns SSE lines from upstream."""
        chunks = _make_stream_chunks("Hi")
        sse_lines = _sse_lines(chunks)

        mock_post.return_value = make_mock_response(200, iter_lines_data=sse_lines)

        r = client.post(
            "/v1/chat/completions",
            headers={"Authorization": f"Bearer {user_key}"},
            json={
                "model": "mimo-v2.5-pro",
                "messages": [{"role": "user", "content": "Hello"}],
                "stream": True,
            },
        )
        assert r.status_code == 200
        assert r.content_type.startswith("text/event-stream")

        # Parse the response body as SSE
        body = r.get_data(as_text=True)
        assert "data:" in body


class TestChatCompletionsValidation:
    """Test input validation for chat completions."""

    def test_missing_model_returns_400(self, client, user_key):
        """Request without model should return 400."""
        r = client.post(
            "/v1/chat/completions",
            headers={"Authorization": f"Bearer {user_key}"},
            json={"messages": [{"role": "user", "content": "Hi"}]},
        )
        assert r.status_code == 400

    def test_invalid_model_returns_400(self, client, user_key):
        """Request with unknown model should return 400."""
        r = client.post(
            "/v1/chat/completions",
            headers={"Authorization": f"Bearer {user_key}"},
            json={
                "model": "gpt-4",
                "messages": [{"role": "user", "content": "Hi"}],
            },
        )
        assert r.status_code == 400

    def test_missing_messages_returns_400(self, client, user_key):
        """Request without messages should return 400."""
        r = client.post(
            "/v1/chat/completions",
            headers={"Authorization": f"Bearer {user_key}"},
            json={"model": "mimo-v2.5-pro"},
        )
        assert r.status_code == 400


class TestChatCompletionsToolCalling:
    """Test tool calling passthrough."""

    @patch("upstream.client.requests.post")
    def test_tools_forwarded_to_upstream(self, mock_post, client, user_key):
        """Tools in request are forwarded to upstream."""
        upstream_resp = _make_chat_response()
        upstream_resp["choices"][0]["message"]["tool_calls"] = [
            {
                "id": "call_abc123",
                "type": "function",
                "function": {
                    "name": "get_weather",
                    "arguments": "{\"location\": \"Tokyo\"}",
                },
            }
        ]
        mock_post.return_value = make_mock_response(200, json_body=upstream_resp)

        tools = [
            {
                "type": "function",
                "function": {
                    "name": "get_weather",
                    "description": "Get weather",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "location": {"type": "string"},
                        },
                    },
                },
            }
        ]

        r = client.post(
            "/v1/chat/completions",
            headers={"Authorization": f"Bearer {user_key}"},
            json={
                "model": "mimo-v2.5-pro",
                "messages": [{"role": "user", "content": "Weather in Tokyo?"}],
                "tools": tools,
                "tool_choice": "auto",
            },
        )
        assert r.status_code == 200
        data = r.get_json()
        assert "tool_calls" in data["choices"][0]["message"]
        assert data["choices"][0]["message"]["tool_calls"][0]["function"]["name"] == "get_weather"

class TestChatCompletionsBudgetMode:
    """Test budget mode integration through /v1/chat/completions endpoint."""

    @patch("upstream.client.requests.post")
    def test_budget_mode_strips_reasoning_effort(self, mock_post, client, user_key):
        """Budget mode should strip reasoning_effort from upstream payload."""
        upstream_resp = _make_chat_response(" terse response")
        mock_post.return_value = make_mock_response(200, json_body=upstream_resp)

        r = client.post(
            "/v1/chat/completions",
            headers={"Authorization": f"Bearer {user_key}"},
            json={
                "model": "mimo-v2.5-pro",
                "messages": [{"role": "user", "content": "Hello"}],
                "reasoning_effort": "budget",
            },
        )
        assert r.status_code == 200

        # Verify upstream payload does NOT have reasoning_effort
        call_kwargs = mock_post.call_args
        payload = call_kwargs.kwargs.get("json", call_kwargs[1].get("json", {}))
        assert "reasoning_effort" not in payload

    @patch("upstream.client.requests.post")
    def test_budget_mode_injects_caveman(self, mock_post, client, user_key):
        """Budget mode should inject caveman system prompt."""
        upstream_resp = _make_chat_response()
        mock_post.return_value = make_mock_response(200, json_body=upstream_resp)

        r = client.post(
            "/v1/chat/completions",
            headers={"Authorization": f"Bearer {user_key}"},
            json={
                "model": "mimo-v2.5-pro",
                "messages": [{"role": "user", "content": "Hello"}],
                "reasoning_effort": "budget",
            },
        )
        assert r.status_code == 200

        # Verify first message is system with caveman prompt
        call_kwargs = mock_post.call_args
        payload = call_kwargs.kwargs.get("json", call_kwargs[1].get("json", {}))
        messages = payload["messages"]
        assert messages[0]["role"] == "system"
        assert "caveman" in messages[0]["content"].lower()

    @patch("upstream.client.requests.post")
    def test_non_budget_passthrough(self, mock_post, client, user_key):
        """Non-budget request should pass reasoning_effort through."""
        upstream_resp = _make_chat_response()
        mock_post.return_value = make_mock_response(200, json_body=upstream_resp)

        r = client.post(
            "/v1/chat/completions",
            headers={"Authorization": f"Bearer {user_key}"},
            json={
                "model": "mimo-v2.5-pro",
                "messages": [{"role": "user", "content": "Hello"}],
                "reasoning_effort": "high",
            },
        )
        assert r.status_code == 200

        # "high" is a valid value — forwarded to upstream as-is
        call_kwargs = mock_post.call_args
        payload = call_kwargs.kwargs.get("json", call_kwargs[1].get("json", {}))
        assert payload.get("reasoning_effort") == "high"

    @patch("upstream.client.requests.post")
    def test_budget_mode_compresses_tool_output(self, mock_post, client, user_key):
        """Budget mode should compress long tool call outputs."""
        upstream_resp = _make_chat_response()
        mock_post.return_value = make_mock_response(200, json_body=upstream_resp)

        long_ls_output = "\n".join(
            f"-rw-r--r--  1 user group {i*100} Jan 01 file_{i}.py"
            for i in range(50)
        )

        r = client.post(
            "/v1/chat/completions",
            headers={"Authorization": f"Bearer {user_key}"},
            json={
                "model": "mimo-v2.5-pro",
                "messages": [
                    {"role": "user", "content": "list files"},
                    {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [{
                            "id": "call_001",
                            "type": "function",
                            "function": {"name": "bash", "arguments": "{\"command\": \"ls\"}"},
                        }],
                    },
                    {
                        "role": "tool",
                        "tool_call_id": "call_001",
                        "content": long_ls_output,
                    },
                    {"role": "user", "content": "summarize"},
                ],
                "reasoning_effort": "budget",
            },
        )
        assert r.status_code == 200

        # Verify tool output was compressed
        call_kwargs = mock_post.call_args
        payload = call_kwargs.kwargs.get("json", call_kwargs[1].get("json", {}))
        # Find the tool message in payload
        tool_msgs = [m for m in payload["messages"] if m.get("role") == "tool"]
        assert len(tool_msgs) == 1
        # Compressed should be shorter than original
        assert len(tool_msgs[0]["content"]) < len(long_ls_output)
