import gzip
import json
import logging

import requests
from config import UPSTREAM_URL, get_upstream_auth
from upstream.errors import classify_error

logger = logging.getLogger(__name__)

# GZIP magic bytes
_GZIP_MAGIC = b'\x1f\x8b'


def _safe_read_response(resp):
    """
    Read the full response body safely, handling the case where upstream
    claims Content-Encoding: gzip but sends uncompressed data.
    """
    # Use resp.raw (urllib3) with decode_content=False to get raw bytes
    # without automatic gzip decompression.
    raw = resp.raw.read()
    resp.raw._fp = None  # prevent further reads

    content_encoding = resp.headers.get('Content-Encoding', '').lower()
    if content_encoding == 'gzip' and raw[:2] == _GZIP_MAGIC:
        try:
            raw = gzip.decompress(raw)
        except Exception:
            logger.warning("Content-Encoding says gzip and magic bytes match, but decompression failed; using raw bytes")
    elif content_encoding == 'gzip' and raw[:2] != _GZIP_MAGIC:
        logger.debug("Upstream sent Content-Encoding: gzip but body is not gzipped, using raw bytes")

    return raw


def iter_sse_lines(resp):
    """
    Iterate SSE lines from a streaming response, safely handling gzip encoding.
    Yields decoded text lines.
    """
    content_encoding = resp.headers.get('Content-Encoding', '').lower()
    needs_gzip_check = 'gzip' in content_encoding

    buf = b''
    for chunk in resp.iter_content(chunk_size=8192):
        if needs_gzip_check:
            # For streaming, gzip is tricky — SSE is typically not gzipped chunk-by-chunk.
            # If the first chunk has gzip magic bytes, we need to buffer and decompress.
            # But SSE streams are usually not gzipped. If upstream lies about encoding,
            # just decode as UTF-8.
            if chunk[:2] == _GZIP_MAGIC:
                # Actually gzipped — buffer everything
                buf += chunk
                for remaining in resp.iter_content(chunk_size=8192):
                    buf += remaining
                try:
                    buf = gzip.decompress(buf)
                except Exception:
                    pass
                text = buf.decode('utf-8', errors='replace')
                for line in text.splitlines():
                    yield line
                return
            else:
                # Not actually gzipped, decode chunks as UTF-8
                needs_gzip_check = False

        buf += chunk
        while b'\n' in buf:
            line, buf = buf.split(b'\n', 1)
            yield line.decode('utf-8', errors='replace')

    # Flush remaining buffer
    if buf:
        yield buf.decode('utf-8', errors='replace')


def call_upstream(payload, stream=False, timeout=120):
    """
    Send request to upstream.
    stream=True: return raw requests.Response for SSE iteration
    stream=False: return parsed JSON dict
    """
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {get_upstream_auth()}",
    }

    # Always use stream=True so requests doesn't auto-decode content.
    # We handle decompression ourselves.
    resp = requests.post(
        UPSTREAM_URL,
        headers=headers,
        json=payload,
        stream=True,
        timeout=timeout,
    )

    if resp.status_code >= 400:
        classify_error(resp)

    if stream:
        return resp

    raw = _safe_read_response(resp)
    return json.loads(raw)
