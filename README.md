# AI Proxy

An OpenAI-compatible Flask gateway that exports `/v1/chat/completions` and
`/v1/responses` and forwards every request to a single upstream Chat
Completions endpoint.

The upstream natively supports **full context**, **tool calling**, and
**streaming**, so this proxy is intentionally thin: no system-prompt tool
emulation, no context distillation, no multi-provider fallbacks. Just clean
authentication, format conversion (Responses API ↔ Chat Completions), and SSE
passthrough.

**Budget Mode** (`reasoning_effort="budget"`) enables automatic token
optimization: tool output compression, debug noise summarization, chat
history focal-point extraction, error deduplication with migration, and a
terse "caveman" system prompt — all with zero overhead when not activated.

---

## Features

- 🔌 **OpenAI-compatible API** — drop-in for Chat Completions and Responses
  endpoints; works with the OpenAI SDK, Continue.dev, Cursor, etc.
- 🔀 **Streaming passthrough** — SSE chunks are forwarded directly from upstream
  with minimal buffering.
- 🛠️ **Native tool calling** — `tools`, `tool_choice`, and `parallel_tool_calls`
  are forwarded as-is; tool-call results in history are also passed through.
- 📦 **Responses API** — server-side conversion between the Responses API
  (`/v1/responses`) and the Chat Completions format the upstream speaks.
- 🔑 **API key management** — SQLite-backed per-key quota with admin CRUD
  endpoints.
- 📦 **Guest mode** — leaving `UPSTREAM_API_KEY` empty automatically uses
  `Bearer guest`, so the proxy works out of the box.
- 🧠 **Budget mode** — auto cache + compression pipeline triggered by
  `reasoning_effort="budget"`:
  - Rule-based tool output compression (ls→filenames, grep→summary, etc.)
  - LRU cache with delta support (only sends changes)
  - LLM-powered debug noise summarization & history focal-point extraction
  - Error deduplication with migration (same error, multiple locations)
  - Caveman prompt injection for terse responses
- 📊 **Request logging** — every request is recorded (endpoint, model, status,
  latency) in SQLite.
- 🧪 **Tested** — 162 pytest tests covering auth, upstream client, Chat
  Completions, Responses, budget mode, compression, caching, and dedup.
- 🚀 **Production-ready** — Gunicorn config + systemd unit file included.

---

## Quick Start

### 1. Clone and set up a virtual environment

```bash
git clone https://github.com/your-org/ai-proxy.git
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure `.env`

Copy the template and edit it:

```bash
cp .env.example .env
$EDITOR .env
```

Minimum useful configuration:

```env
UPSTREAM_URL=https://your-upstream.example.com/v1/chat/completions
UPSTREAM_API_KEY=your-upstream-key       # leave empty for guest mode
ADMIN_API_KEY=sk-your-admin-key-here     # MUST be set in production
KEY_PREFIX=sk-prod
DB_PATH=api_keys.db
LOG_LEVEL=INFO
```

### 3. Run the server

Development (Flask built-in, port 80 — may need `sudo` or `setcap`):

```bash
python main.py
```

Or with Gunicorn (recommended for anything beyond local testing):

```bash
venv/bin/gunicorn -c gunicorn.conf.py "app:create_app()"
```

### 4. Smoke test

```bash
curl http://localhost/health
# {"status": "ok"}

curl http://localhost/v1/models
# {"object": "list", "data": [...]}
```

### 5. Create an API key

```bash
curl -X POST http://localhost/v1/admin/api/create \
  -H "Authorization: Bearer $ADMIN_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"uses": 100, "admin": 0}'
# {"key": "sk-prod-..."}
```

Use that key to call Chat Completions:

```bash
curl -X POST http://localhost/v1/chat/completions \
  -H "Authorization: Bearer sk-prod-..." \
  -H "Content-Type: application/json" \
  -d '{
    "model": "mimo-v2.5-pro",
    "messages": [{"role": "user", "content": "Hello!"}]
  }'
```

### 6. Try Budget Mode

Add `"reasoning_effort": "budget"` to your request to activate the
compression pipeline:

```bash
curl -X POST http://localhost/v1/chat/completions \
  -H "Authorization: Bearer sk-prod-..." \
  -H "Content-Type: application/json" \
  -d '{
    "model": "mimo-v2.5-pro",
    "messages": [{"role": "user", "content": "Hello!"}],
    "reasoning_effort": "budget"
  }'
```

---

## API Endpoints

| Method | Path                       | Auth         | Description                                          |
| ------ | -------------------------- | ------------ | ---------------------------------------------------- |
| GET    | `/health`                  | none         | Liveness probe — returns `{"status": "ok"}`.        |
| GET    | `/v1/health`               | none         | Alias of `/health`.                                  |
| GET    | `/v1/models`               | none         | OpenAI-style model list (5 hardcoded `mimo-*`).      |
| POST   | `/v1/chat/completions`     | API key      | Chat Completions — stream and non-stream.           |
| POST   | `/v1/responses`            | API key      | Responses API — converted to/from Chat Completions. |
| GET    | `/v1/usage`                | none         | Markdown API documentation.                          |
| GET    | `/v1/status`               | API key      | Returns the caller's own key info (uses, admin).     |
| POST   | `/v1/admin/api/create`     | Admin key    | Create a new API key.                                |
| GET    | `/v1/admin/api/list`       | Admin key    | List all API keys.                                   |
| POST   | `/v1/admin/api/edit`       | Admin key    | Edit an API key (e.g. change `uses`).                |
| POST   | `/v1/admin/api/delete`     | Admin key    | Delete an API key.                                   |
| GET    | `/v1/admin/logs`           | Admin key    | View recent request logs.                            |

**Auth column legend:**
- _none_ — no `Authorization` header required
- _API key_ — any valid key in the DB (admin or non-admin)
- _Admin key_ — a key with `admin=1` (or the `ADMIN_API_KEY` from `.env`)

### Supported models

Hardcoded in `models/registry.py` (the upstream doesn't expose `/v1/models`):

- `mimo-v2.5-pro`
- `mimo-v2.5`
- `mimo-v2-pro`
- `mimo-v2-flash`
- `mimo-v2-omni`

Edit `models/registry.py` to add or change models for your upstream.

---

## Configuration (`.env`)

| Variable                  | Default                                      | Description                                                                                              |
| ------------------------- | -------------------------------------------- | -------------------------------------------------------------------------------------------------------- |
| `UPSTREAM_URL`            | `http://localhost:11434/v1/chat/completions` | Upstream Chat Completions endpoint.                                                                      |
| `UPSTREAM_API_KEY`        | _(empty)_                                    | Bearer token for upstream. Leave empty to use **guest mode** (proxy sends `Bearer guest`).               |
| `ADMIN_API_KEY`           | _(empty)_                                    | Bootstrap admin key. Always treated as admin even if not in DB. **MUST be set in production.**           |
| `KEY_PREFIX`              | `sk-proxy`                                   | Prefix used when generating new API keys.                                                                |
| `DB_PATH`                 | `api_keys.db`                                | Path to the SQLite database file.                                                                        |
| `LOG_LEVEL`               | `INFO`                                       | Python logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`).                                              |
| `PORT`                    | `80`                                         | Port the dev server (`python main.py`) listens on. Gunicorn's port is controlled by `gunicorn.conf.py`. |
| `BUDGET_ENABLED`          | `true`                                       | Enable/disable budget mode compression pipeline.                                                         |
| `BUDGET_CACHE_SIZE`       | `256`                                        | LRU cache max entries.                                                                                    |
| `BUDGET_CACHE_TTL`        | `3600`                                       | Cache entry TTL in seconds.                                                                               |
| `BUDGET_HISTORY_KEEP_N`  | `4`                                          | Number of recent messages to keep uncompressed.                                                           |
| `BUDGET_COMPRESS_THRESHOLD` | `500`                                      | Minimum characters to trigger tool output compression.                                                    |

---

## Testing

The pytest suite mocks the upstream so no network calls are needed.

```bash
source venv/bin/activate
pytest -v
```

162 tests covering:

- `tests/test_health.py` — `/health` endpoint
- `tests/test_auth.py` — auth middleware, API key CRUD, `/v1/status`
- `tests/test_upstream.py` — upstream client, error classification (mocked)
- `tests/test_chat.py` — `/v1/chat/completions` (non-stream, stream, tool calls,
  validation, budget mode)
- `tests/test_responses.py` — `/v1/responses` (format conversion, streaming,
  budget mode)
- `tests/test_models.py` — `/v1/models` and the model registry
- `tests/test_budget_*.py` — budget mode trigger, pipeline, compression modules
- `tests/test_cache.py` — LRU cache and delta engine
- `tests/test_compress_*.py` — tool output, debug noise, history, dedup

---

## Deployment (systemd)

1. **Install the venv and dependencies** on the target host:

   ```bash
   cd /opt/ai-proxy
   python3 -m venv venv
   venv/bin/pip install -r requirements.txt
   ```

2. **Create `.env`** in the project root (see _Configuration_ above).

3. **Edit the systemd unit file** (`ai-proxy.service`) to match your paths and
   user, then install it:

   ```bash
   sudo cp ai-proxy.service /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable --now ai-proxy
   ```

4. **Inspect logs / status:**

   ```bash
   sudo systemctl status ai-proxy
   sudo journalctl -u ai-proxy -f
   ```

### Why a single Gunicorn worker?

The `api_keys.db` SQLite database is accessed for every authenticated request
(quota check, request logging). Multiple worker processes would risk
`database is locked` errors. We instead use **one process with 4 threads**
(`worker_class = "gthread"`), which is plenty given that most of the
request lifetime is spent waiting on the upstream and that SSE streaming is
non-blocking from Gunicorn's perspective.

---

## Architecture

See [ARCHITECTURE.md](./ARCHITECTURE.md) for the full design document covering:

- High-level system diagram
- Module structure (`auth/`, `upstream/`, `endpoints/`, `format/`, `models/`,
  `db/`, `budget/`, `cache/`, `compress/`)
- Request flow for Chat Completions and Responses (streaming and non-streaming)
- Budget mode compression pipeline
- Format-conversion rules between the Responses API and Chat Completions
- Database schema
- Key design decisions

A brief sketch of the runtime flow:

```
Client ──POST /v1/chat/completions──▶ Auth middleware (API key + quota)
                                    ──▶ Validate model
                                    ──▶ Budget mode? → compress pipeline
                                    ──▶ upstream.client.call_upstream(...)
                                                 ──▶ UPSTREAM_URL
                                    ◀── SSE chunks / JSON
                                    ──▶ (Responses API: convert chunk format)
                                    ──▶ Yield to client
                                    ──▶ After-request: log to SQLite
```

---

## License

MIT License. See [LICENSE](./LICENSE) for details.