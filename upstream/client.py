import requests
from config import UPSTREAM_URL, get_upstream_auth
from upstream.errors import classify_error


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

    resp = requests.post(
        UPSTREAM_URL,
        headers=headers,
        json=payload,
        stream=stream,
        timeout=timeout,
    )

    if resp.status_code >= 400:
        classify_error(resp)

    if stream:
        return resp
    return resp.json()
