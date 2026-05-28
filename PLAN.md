# Implementation Plan — OpenGateway AI Proxy

## Tổng quan

Migrate từ base `ai_proxy` (3400 dòng, 1 file) sang kiến trúc modular cho OpenGateway upstream.
Mỗi phase có deliverable chạy được + tests pass.

---

## Phase 0: Project Bootstrap
**Goal**: Tạo workspace, init git, cài dependencies.

### Tasks
- [x] Tạo thư mục `/home/exedev/opengateway_ai_proxy`
- [x] `git init`
- [x] Viết `ARCHITECTURE.md`
- [x] Viết `PLAN.md`
- [ ] Tạo `requirements.txt`
- [ ] Tạo `.env.example`
- [ ] Tạo `.gitignore`
- [ ] Initial commit

### Files
```
requirements.txt
.env.example
.gitignore
```

### `requirements.txt`
```
flask>=3.0
requests>=2.31
python-dotenv>=1.0
pytest>=8.0
gunicorn>=21.2
```

### `.env.example`
```
UPSTREAM_URL=https://opengateway.gitlawb.com/v1/chat/completions
# Để trống = guest mode (tự gửi Bearer guest lên upstream)
UPSTREAM_API_KEY=
ADMIN_API_KEY=sk-quangdz-admin-ai
KEY_PREFIX=sk-quangdz
DB_PATH=api_keys.db
```

### `.gitignore`
```
__pycache__/
*.pyc
.env
api_keys.db
*.db
.pytest_cache/
node_modules/
venv/
```

---

## Phase 1: Core Infrastructure
**Goal**: Flask app chạy được, config load, DB init, health endpoint.

### Tasks
- [ ] `config.py` — load env, constants
- [ ] `db/database.py` — SQLite connection, schema init
- [ ] `db/schema.sql` — table definitions
- [ ] `app.py` — Flask app factory
- [ ] `endpoints/health.py` — `/health` endpoint
- [ ] `main.py` — entrypoint
- [ ] Test: `pytest tests/test_health.py`

### Files
```
config.py
db/__init__.py
db/database.py
db/schema.sql
app.py
main.py
endpoints/__init__.py
endpoints/health.py
tests/__init__.py
tests/conftest.py
tests/test_health.py
```

### Implementation Details

**`config.py`**:
```python
import os
from dotenv import load_dotenv

load_dotenv()

UPSTREAM_URL = os.getenv("UPSTREAM_URL", "https://opengateway.gitlawb.com/v1/chat/completions")
UPSTREAM_API_KEY = os.getenv("UPSTREAM_API_KEY", "")  # empty → guest mode
GUEST_API_KEY = "guest"  # fallback when UPSTREAM_API_KEY is empty
ADMIN_API_KEY = os.getenv("ADMIN_API_KEY", "sk-quangdz-admin-ai")
KEY_PREFIX = os.getenv("KEY_PREFIX", "sk-quangdz")
DB_PATH = os.getenv("DB_PATH", "api_keys.db")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

def get_upstream_auth():
    """Return the Bearer token for upstream. Falls back to 'guest' if no key configured."""
    return UPSTREAM_API_KEY if UPSTREAM_API_KEY else GUEST_API_KEY
```

**`db/schema.sql`**:
```sql
CREATE TABLE IF NOT EXISTS api_keys (
    key TEXT PRIMARY KEY,
    uses INTEGER DEFAULT -1,
    admin INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS request_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    api_key TEXT,
    endpoint TEXT,
    model TEXT,
    stream INTEGER DEFAULT 0,
    status INTEGER DEFAULT 200,
    latency_ms INTEGER DEFAULT 0,
    error TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);
```

**`app.py`**:
```python
from flask import Flask
from config import LOG_LEVEL
import logging

def create_app():
    app = Flask(__name__)
    logging.basicConfig(level=LOG_LEVEL)
    
    from db.database import init_db
    init_db()
    
    from endpoints.health import health_bp
    app.register_blueprint(health_bp)
    
    return app
```

### Acceptance Criteria
- `python main.py` starts Flask server on port 80
- `GET /health` returns `{"status": "ok"}`
- `api_keys.db` created automatically
- `pytest tests/test_health.py` passes

---

## Phase 2: Authentication & Admin
**Goal**: API key auth middleware + admin CRUD endpoints.

### Tasks
- [ ] `auth/middleware.py` — before_request auth hook
- [ ] `auth/api_keys.py` — DB operations for keys
- [ ] `endpoints/admin.py` — CRUD endpoints
- [ ] Register middleware & admin blueprint in `app.py`
- [ ] Test: `pytest tests/test_auth.py`

### Files
```
auth/__init__.py
auth/middleware.py
auth/api_keys.py
endpoints/admin.py
tests/test_auth.py
```

### Implementation Details

**`auth/middleware.py`**:
- `@app.before_request` hook
- Parse `Authorization: Bearer <key>`
- Skip auth cho public endpoints: `/health`, `/v1/models`
- Validate key in DB, check quota
- Set `g.api_key`, `g.is_admin`, `g.start_time`
- Trừ `uses` nếu != -1 (unlimited)

**`auth/api_keys.py`**:
```python
def create_key(uses=-1, admin=0, prefix="sk-quangdz") -> str
def get_key(key: str) -> dict | None
def decrement_uses(key: str) -> bool
def list_keys() -> list[dict]
def edit_key(key: str, **kwargs) -> bool
def delete_key(key: str) -> bool
def log_request(api_key, endpoint, model, stream, status, latency_ms, error)
```

**`endpoints/admin.py`**:
- `POST /v1/admin/api/create` — tạo key (admin only)
- `GET /v1/admin/api/list` — list all keys (admin only)
- `POST /v1/admin/api/edit` — sửa key (admin only)
- `POST /v1/admin/api/delete` — xóa key (admin only)
- `GET /v1/admin/logs` — xem request logs (admin only)
- `GET /v1/status` — check own key info (bất kỳ user nào)

### Acceptance Criteria
- Request không có API key → 401
- Request với key không tồn tại → 401
- Request với key hết quota (uses=0) → 429
- Admin CRUD hoạt động đầy đủ
- `pytest tests/test_auth.py` passes

---

## Phase 3: Upstream Client
**Goal**: Communication layer với OpenGateway upstream.

### Tasks
- [ ] `upstream/client.py` — HTTP client
- [ ] `upstream/errors.py` — error classification
- [ ] Test với real upstream (manual test first)
- [ ] Unit tests với mocked upstream

### Files
```
upstream/__init__.py
upstream/client.py
upstream/errors.py
tests/test_upstream.py
```

### Implementation Details

**`upstream/client.py`**:
```python
from config import UPSTREAM_URL, get_upstream_auth

def call_upstream(payload: dict, stream: bool = False, timeout: int = 120):
    """
    Send request to upstream.
    If stream=True: returns requests.Response (for SSE iteration)
    If stream=False: returns parsed JSON dict

    Auth: always sends Bearer token.
    - UPSTREAM_API_KEY nếu có
    - 'guest' nếu trống (guest mode)
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
        raise classify_error(resp)
    
    if stream:
        return resp
    return resp.json()
```

**`upstream/errors.py`**:
```python
class UpstreamError(Exception): ...
class RateLimitError(UpstreamError): ...    # 429
class AuthError(UpstreamError): ...         # 401/403
class ModelNotFoundError(UpstreamError): ... # 404
class ServerError(UpstreamError): ...       # 5xx
def classify_error(resp) -> UpstreamError: ...
```

### Acceptance Criteria
- `call_upstream({"model": "...", "messages": [...], "stream": false})` returns JSON
- `call_upstream({"model": "...", "messages": [...], "stream": true})` returns iterable Response
- Error codes mapped correctly to exceptions
- Unit tests pass with mocked `requests.post`

---

## Phase 4: Chat Completions Endpoint
**Goal**: `/v1/chat/completions` hoạt động cho cả streaming và non-streaming.

### Tasks
- [ ] `endpoints/chat.py` — chat completions handler
- [ ] `models/registry.py` — model name resolution
- [ ] `format/sse.py` — SSE helpers
- [ ] Register blueprint in `app.py`
- [ ] Test: `pytest tests/test_chat.py`
- [ ] Test: `node tests/test_streaming.mjs` (OpenAI SDK)

### Files
```
models/__init__.py
models/registry.py
format/__init__.py
format/sse.py
endpoints/chat.py
tests/test_chat.py
tests/test_streaming.mjs
```

### Implementation Details

**`models/registry.py`** (hardcoded — upstream không có /v1/models):
```python
MODELS = [
    "mimo-v2.5-pro",
    "mimo-v2.5",
    "mimo-v2-pro",
    "mimo-v2-flash",
    "mimo-v2-omni",
]

MODEL_SET = set(MODELS)

def resolve_model(name: str) -> str:
    """Validate model name against hardcoded list."""
    if not name:
        raise ValueError("Model name is required")
    if name not in MODEL_SET:
        raise ValueError(f"Unknown model: {name}. Available: {', '.join(MODELS)}")
    return name
```

**`format/sse.py`**:
```python
from flask import Response

def sse_response(generator):
    """Wrap a generator as SSE Flask Response."""
    return Response(generator, mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

def parse_sse_lines(resp):
    """Yield parsed SSE data from upstream response."""
    for line in resp.iter_lines(decode_unicode=True):
        if line.startswith("data: "):
            data = line[6:]
            if data == "[DONE]":
                return
            yield data
```

**`endpoints/chat.py`**:

Non-streaming:
1. Validate body (model, messages required)
2. Resolve model
3. Call upstream with `stream=false`
4. Return upstream JSON response directly

Streaming:
1. Validate body
2. Resolve model
3. Call upstream with `stream=true`
4. Generator: iterate upstream SSE lines, yield each line directly
5. After stream ends, yield `data: [DONE]`
6. After_request hook logs the request

### Acceptance Criteria
- `POST /v1/chat/completions` non-stream returns valid OpenAI format
- `POST /v1/chat/completions` stream returns SSE with correct format
- Tool calling passthrough (tools in request → tool_calls in response)
- `stream_options: {include_usage: true}` passthrough
- Multi-turn conversation works
- Node.js OpenAI SDK tests pass (dùng mimo-v2.5 model)

---

## Phase 5: Responses API Endpoint
**Goal**: `/v1/responses` hoạt động, convert giữa Responses format và Chat Completions.

### Tasks
- [ ] `format/responses_api.py` — conversion helpers
- [ ] `endpoints/responses.py` — responses handler
- [ ] Register blueprint in `app.py`
- [ ] Test: `pytest tests/test_responses.py`
- [ ] Test: `node tests/test_continue.mjs` (Continue.dev patterns)

### Files
```
format/responses_api.py
endpoints/responses.py
tests/test_responses.py
tests/test_continue.mjs
```

### Implementation Details

**`format/responses_api.py`**:

Core conversion functions (kế thừa logic từ base cũ `_responses_input_to_messages`, `_build_response_object`):

```python
def responses_input_to_messages(body: dict) -> list[dict]:
    """Convert Responses API input → Chat Completions messages."""
    # input can be: string | array of message items
    # Handle: role messages, function_call items, function_call_output items
    # Handle: content as string or array of parts [{type: "input_text", text: "..."}]
    # instructions → system message prepended
    ...

def responses_tools_to_cc_tools(tools: list) -> list:
    """Convert Responses API tools → Chat Completions tools format."""
    # Responses: {"type": "function", "name": "...", "parameters": {...}}
    # CC: {"type": "function", "function": {"name": "...", "parameters": {...}}}
    ...

def build_response_object(resp_id, model, output_items, created_at, status, usage):
    """Build non-streaming Responses API response object."""
    ...

def build_response_events(resp_id, model, chunk, created_at):
    """Convert Chat Completions streaming chunk → Responses API events list."""
    # Text content → response.output_text.delta / .done
    # Tool calls → response.output_item.added / function_call_arguments.delta / .done / output_item.done
    # Finish → response.completed
    ...
```

**`endpoints/responses.py`**:

Non-streaming:
1. Parse body, convert input → messages, tools → CC tools
2. Call upstream with `stream=false`
3. Convert upstream CC response → Responses API format
4. Return

Streaming:
1. Parse body, convert input → messages, tools → CC tools
2. Call upstream with `stream=true`
3. Generator: yield initial events (response.created, response.in_progress)
4. For each upstream SSE chunk, convert to Responses events and yield
5. Yield final response.completed event

### Acceptance Criteria
- `POST /v1/responses` non-stream returns valid Responses API format
- `POST /v1/responses` stream returns SSE with correct event types
- `instructions` parameter → system message
- Array input with history works
- Content as array of parts works
- Tool calling (function_call items) convert correctly
- Node.js OpenAI SDK `responses.create()` works
- Continue.dev compatibility tests pass

---

## Phase 6: Models Endpoint & Polish
**Goal**: `/v1/models`, request logging, error handling, production readiness.

### Tasks
- [ ] `endpoints/models.py` — models list endpoint
- [ ] After_request logging middleware
- [ ] Global error handler
- [ ] README.md
- [ ] Integration test: full flow
- [ ] Final cleanup & commit

### Files
```
endpoints/models.py
tests/test_models.py
README.md
```

### Implementation Details

**`endpoints/models.py`**:
- `GET /v1/models` → return hardcoded model list from registry
- Format: OpenAI models list format (`object: "list"`, `data: [{id, object, created, owned_by}]`)
- Upstream không có /v1/models nên không thể fetch dynamic

**After_request middleware** (in `auth/middleware.py`):
- Log every request to `request_log` table
- Include: api_key, endpoint, model, stream, status, latency_ms, error

**Global error handler**:
```python
@app.errorhandler(Exception)
def handle_exception(e):
    if isinstance(e, UpstreamError):
        return jsonify({"error": {"type": "upstream_error", "message": str(e)}}), 502
    return jsonify({"error": {"type": "server_error", "message": str(e)}}), 500
```

### Acceptance Criteria
- `GET /v1/models` returns model list
- Request logging works for all endpoints
- Unhandled exceptions return JSON error, not HTML
- README.md có hướng dẫn setup & run
- All tests pass: `pytest` + `node test_*.mjs`

---

## Phase 7: Deployment & Systemd
**Goal**: Production deployment trên VM.

### Tasks
- [ ] Gunicorn config
- [ ] Systemd unit file
- [ ] Test production setup
- [ ] Final commit

### Files
```
gunicorn.conf.py
opengateway-ai-proxy.service
```

### Acceptance Criteria
- `sudo systemctl start opengateway-ai-proxy` runs successfully
- Proxy accessible on configured port
- SSE streaming works through production server

---

## Dependency Graph

```
Phase 0 (Bootstrap)
  └── Phase 1 (Core: config, db, health)
        ├── Phase 2 (Auth & Admin)
        │     └── Phase 3 (Upstream Client)
        │           ├── Phase 4 (Chat Completions)
        │           │     └── Phase 6 (Polish)
        │           └── Phase 5 (Responses API)
        │                 └── Phase 6 (Polish)
        └── Phase 6 (Polish) ← can start earlier
  └── Phase 7 (Deployment) ← after all phases
```

Phases 4 and 5 can be developed in parallel after Phase 3.

---

## Test Strategy

### Python Unit Tests (pytest)
- `test_health.py` — health endpoint
- `test_auth.py` — auth middleware, API key CRUD
- `test_upstream.py` — upstream client (mocked)
- `test_chat.py` — chat completions handler (mocked upstream)
- `test_responses.py` — format conversion, responses handler
- `test_models.py` — model registry, models endpoint

### Node.js Integration Tests (OpenAI SDK)
- `test_streaming.mjs` — streaming/non-streaming chat completions
- `test_continue.mjs` — Continue.dev exact patterns
- `test_responses_gpt.mjs` — Responses API with various params
- `test_tools.mjs` — Tool calling passthrough

### Manual Smoke Tests
- `curl` test các endpoint cơ bản
- Verify SSE stream format
- Test với Continue.dev / Cursor client
