"""Shared test helpers."""
import json
from unittest.mock import MagicMock, PropertyMock


def make_mock_response(status_code=200, json_body=None, iter_lines_data=None):
    """Build a mock requests.Response that works with raw-based reading.
    
    json_body: dict — response will return its bytes via resp.raw.read()
    iter_lines_data: list[str] — SSE lines returned via iter_content
    """
    resp = MagicMock()
    resp.status_code = status_code
    resp.ok = 200 <= status_code < 400
    resp.headers = {}
    
    if json_body is not None:
        body_bytes = json.dumps(json_body).encode('utf-8')
        resp.raw.read.return_value = body_bytes
        resp.raw._fp = None
        resp.iter_content.return_value = [body_bytes]
        resp.json.return_value = json_body
        resp.text = json.dumps(json_body)
    elif iter_lines_data is not None:
        full_text = '\n'.join(iter_lines_data)
        body_bytes = full_text.encode('utf-8')
        resp.raw.read.return_value = body_bytes
        resp.raw._fp = None
        resp.iter_content.return_value = [body_bytes]
        resp.iter_lines.return_value = iter_lines_data
    else:
        resp.raw.read.return_value = b'{}'
        resp.raw._fp = None
        resp.iter_content.return_value = [b'{}']
    
    return resp
