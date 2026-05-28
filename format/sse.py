from flask import Response


def sse_response(generator):
    """Wrap a generator as SSE Flask Response."""
    return Response(
        generator,
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


def parse_sse_lines(resp):
    """Yield parsed SSE data strings from upstream response."""
    for line in resp.iter_lines(decode_unicode=True):
        if not line:
            continue
        if line.startswith("data: "):
            data = line[6:]
            if data == "[DONE]":
                return
            yield data
