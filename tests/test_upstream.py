"""Tests for upstream client with mocked requests.post."""
import json
import pytest
from unittest.mock import patch, MagicMock

from upstream.client import call_upstream
from upstream.errors import (
    UpstreamError,
    RateLimitError,
    AuthError,
    ModelNotFoundError,
    ServerError,
    classify_error,
)


def _mock_response(status_code=200, json_body=None, iter_lines_data=None):
    """Build a mock requests.Response object."""
    resp = MagicMock()
    resp.status_code = status_code
    if json_body is not None:
        resp.json.return_value = json_body
    if iter_lines_data is not None:
        resp.iter_lines.return_value = iter_lines_data
    resp.ok = 200 <= status_code < 400
    return resp


class TestCallUpstreamNonStream:
    """Test call_upstream with stream=False (default)."""

    @patch("upstream.client.requests.post")
    def test_returns_parsed_json(self, mock_post):
        """Non-stream call returns the parsed JSON from upstream."""
        upstream_resp = {
            "id": "chatcmpl-123",
            "object": "chat.completion",
            "model": "mimo-v2.5-pro",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "Hello!"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }
        mock_post.return_value = _mock_response(200, json_body=upstream_resp)

        result = call_upstream({"model": "mimo-v2.5-pro", "messages": [{"role": "user", "content": "Hi"}]})
        assert result == upstream_resp
        assert result["choices"][0]["message"]["content"] == "Hello!"

    @patch("upstream.client.requests.post")
    def test_sends_correct_headers(self, mock_post):
        """Upstream call includes proper Authorization and Content-Type headers."""
        mock_post.return_value = _mock_response(200, json_body={"id": "test"})

        call_upstream({"model": "mimo-v2.5-pro", "messages": []})

        call_kwargs = mock_post.call_args
        headers = call_kwargs.kwargs.get("headers", call_kwargs[1].get("headers", {}))
        assert headers.get("Authorization") == "Bearer test-upstream-key"
        assert headers.get("Content-Type") == "application/json"

    @patch("upstream.client.requests.post")
    def test_sends_payload_as_json(self, mock_post):
        """Payload is sent as JSON body."""
        mock_post.return_value = _mock_response(200, json_body={"id": "test"})

        payload = {"model": "mimo-v2.5", "messages": [{"role": "user", "content": "test"}]}
        call_upstream(payload)

        call_kwargs = mock_post.call_args
        assert call_kwargs.kwargs.get("json", call_kwargs[1].get("json")) == payload

    @patch("upstream.client.requests.post")
    def test_default_timeout(self, mock_post):
        """Default timeout is 120 seconds."""
        mock_post.return_value = _mock_response(200, json_body={"id": "test"})

        call_upstream({"model": "mimo-v2.5", "messages": []})

        call_kwargs = mock_post.call_args
        assert call_kwargs.kwargs.get("timeout", call_kwargs[1].get("timeout")) == 120

    @patch("upstream.client.requests.post")
    def test_custom_timeout(self, mock_post):
        """Custom timeout is forwarded correctly."""
        mock_post.return_value = _mock_response(200, json_body={"id": "test"})

        call_upstream({"model": "mimo-v2.5", "messages": []}, timeout=30)

        call_kwargs = mock_post.call_args
        assert call_kwargs.kwargs.get("timeout", call_kwargs[1].get("timeout")) == 30


class TestCallUpstreamStream:
    """Test call_upstream with stream=True."""

    @patch("upstream.client.requests.post")
    def test_returns_response_object(self, mock_post):
        """Stream call returns a Response object (for iter_lines)."""
        mock_resp = _mock_response(200, iter_lines_data=[])
        mock_post.return_value = mock_resp

        result = call_upstream(
            {"model": "mimo-v2.5-pro", "messages": [], "stream": True},
            stream=True,
        )
        assert result is mock_resp

    @patch("upstream.client.requests.post")
    def test_stream_flag_passed_to_requests(self, mock_post):
        """stream=True is passed to requests.post."""
        mock_resp = _mock_response(200, iter_lines_data=[])
        mock_post.return_value = mock_resp

        call_upstream(
            {"model": "mimo-v2.5-pro", "messages": []},
            stream=True,
        )

        call_kwargs = mock_post.call_args
        assert call_kwargs.kwargs.get("stream", call_kwargs[1].get("stream")) is True


class TestUpstreamErrors:
    """Test error classification from upstream responses."""

    def test_429_raises_rate_limit_error(self):
        """HTTP 429 should raise RateLimitError."""
        resp = _mock_response(429, json_body={"error": "rate limited"})
        with pytest.raises(RateLimitError):
            classify_error(resp)

    def test_401_raises_auth_error(self):
        """HTTP 401 should raise AuthError."""
        resp = _mock_response(401, json_body={"error": "unauthorized"})
        with pytest.raises(AuthError):
            classify_error(resp)

    def test_403_raises_auth_error(self):
        """HTTP 403 should raise AuthError."""
        resp = _mock_response(403, json_body={"error": "forbidden"})
        with pytest.raises(AuthError):
            classify_error(resp)

    def test_404_raises_model_not_found_error(self):
        """HTTP 404 should raise ModelNotFoundError."""
        resp = _mock_response(404, json_body={"error": "not found"})
        with pytest.raises(ModelNotFoundError):
            classify_error(resp)

    def test_500_raises_server_error(self):
        """HTTP 500 should raise ServerError."""
        resp = _mock_response(500, json_body={"error": "internal server error"})
        with pytest.raises(ServerError):
            classify_error(resp)

    def test_502_raises_server_error(self):
        """HTTP 502 should raise ServerError."""
        resp = _mock_response(502, json_body={"error": "bad gateway"})
        with pytest.raises(ServerError):
            classify_error(resp)

    def test_503_raises_server_error(self):
        """HTTP 503 should raise ServerError."""
        resp = _mock_response(503, json_body={"error": "service unavailable"})
        with pytest.raises(ServerError):
            classify_error(resp)

    def test_all_errors_are_upstream_errors(self):
        """All specific errors inherit from UpstreamError."""
        assert issubclass(RateLimitError, UpstreamError)
        assert issubclass(AuthError, UpstreamError)
        assert issubclass(ModelNotFoundError, UpstreamError)
        assert issubclass(ServerError, UpstreamError)

    @patch("upstream.client.requests.post")
    def test_call_upstream_raises_on_429(self, mock_post):
        """call_upstream raises RateLimitError on 429."""
        mock_post.return_value = _mock_response(429, json_body={"error": "rate limit"})
        with pytest.raises(RateLimitError):
            call_upstream({"model": "mimo-v2.5", "messages": []})

    @patch("upstream.client.requests.post")
    def test_call_upstream_raises_on_401(self, mock_post):
        """call_upstream raises AuthError on 401."""
        mock_post.return_value = _mock_response(401, json_body={"error": "unauthorized"})
        with pytest.raises(AuthError):
            call_upstream({"model": "mimo-v2.5", "messages": []})

    @patch("upstream.client.requests.post")
    def test_call_upstream_raises_on_404(self, mock_post):
        """call_upstream raises ModelNotFoundError on 404."""
        mock_post.return_value = _mock_response(404, json_body={"error": "not found"})
        with pytest.raises(ModelNotFoundError):
            call_upstream({"model": "mimo-v2.5", "messages": []})

    @patch("upstream.client.requests.post")
    def test_call_upstream_raises_on_500(self, mock_post):
        """call_upstream raises ServerError on 500."""
        mock_post.return_value = _mock_response(500, json_body={"error": "server error"})
        with pytest.raises(ServerError):
            call_upstream({"model": "mimo-v2.5", "messages": []})

    @patch("upstream.client.requests.post")
    def test_call_upstream_success_200(self, mock_post):
        """call_upstream returns normally on 200."""
        mock_post.return_value = _mock_response(200, json_body={"id": "ok"})
        result = call_upstream({"model": "mimo-v2.5", "messages": []})
        assert result == {"id": "ok"}