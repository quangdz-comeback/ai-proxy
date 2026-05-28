import logging

from flask import Blueprint

from models.registry import get_model_list

logger = logging.getLogger(__name__)

usage_bp = Blueprint("usage", __name__)

USAGE_DOC = """# OpenGateway AI Proxy — API Usage Guide

## Base URL
```
https://<your-domain>
```

## Authentication
All requests (except `/v1/models` and `/v1/usage`) require an API key:
```
Authorization: Bearer <your-api-key>
```

## Supported Models

{models_list}

## Endpoints

### Chat Completions (OpenAI-compatible)
```
POST /v1/chat/completions
```

**Request body:**
```json
{{
  "model": "mimo-v2.5-pro",
  "messages": [
    {{"role": "system", "content": "You are a helpful assistant."}},
    {{"role": "user", "content": "Hello!"}}
  ],
  "stream": false,
  "temperature": 0.7,
  "max_tokens": 1024
}}
```

**Streaming:** Set `"stream": true` for SSE streaming responses.

### Responses API (OpenAI Responses format)
```
POST /v1/responses
```

**Request body:**
```json
{{
  "model": "mimo-v2.5-pro",
  "input": "Hello, how are you?",
  "stream": false,
  "instructions": "You are a helpful assistant."
}}
```

`input` can be a string or an array of message objects.

### List Models
```
GET /v1/models
```
No authentication required. Returns available models.

### Check Status
```
GET /v1/status
```
Returns info about your API key (quota, admin status).

## Admin Endpoints

All admin endpoints require admin API key.

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/v1/admin` | GET | List available admin endpoints |
| `/v1/admin/api/create` | POST | Create new API key |
| `/v1/admin/api/list` | GET | List all API keys |
| `/v1/admin/api/edit` | POST/PATCH/PUT | Edit an API key |
| `/v1/admin/api/delete` | POST/DELETE | Delete an API key |
| `/v1/admin/logs` | GET | View request logs |

### Create Key
```
POST /v1/admin/api/create
```
```json
{{"name": "my-key", "uses": 100, "admin": false}}
```
- `name`: optional display name (auto-generated if omitted)
- `uses`: quota (null/omitted = unlimited, integer = limited)
- `admin`: boolean

### List Keys
```
GET /v1/admin/api/list
```

### Edit Key
```
POST /v1/admin/api/edit
```
```json
{{"key": "sk-xxx", "name": "new-name", "uses": 200, "admin": false}}
```

### Delete Key
```
POST /v1/admin/api/delete
```
```json
{{"key": "sk-xxx"}}
```
or `{{"name": "my-key"}}`

### Request Logs
```
GET /v1/admin/logs?limit=50&key=sk-xxx
```

## SDK Usage (OpenAI Python)

```python
from openai import OpenAI

client = OpenAI(
    base_url="https://<your-domain>/v1",
    api_key="<your-api-key>"
)

response = client.chat.completions.create(
    model="mimo-v2.5-pro",
    messages=[{{"role": "user", "content": "Hello!"}}]
)
print(response.choices[0].message.content)
```
"""


@usage_bp.route("/v1/usage", methods=["GET"])
@usage_bp.route("/usage", methods=["GET"])
def usage_guide():
    """Return API usage guide as Markdown."""
    models = get_model_list()
    models_list = "\n".join(f"- `{m['id']}`" for m in models)
    doc = USAGE_DOC.format(models_list=models_list)
    return doc, 200, {"Content-Type": "text/markdown; charset=utf-8"}
