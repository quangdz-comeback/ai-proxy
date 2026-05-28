# OpenGateway AI Proxy

An OpenAI-compatible Flask gateway that exports `/v1/chat/completions` and
`/v1/responses` and forwards every request to a single upstream:

```
https://opengateway.gitlawb.com/v1/chat/completions
```

The upstream natively supports **full context**, **tool calling**, and
**streaming**, so this proxy is intentionally thin: no system-prompt tool
emulation, no context distillation, no multi-provider fallbacks. Just clean
authentication, format conversion (Responses API ↔ Chat Completions), and SSE
passthrough.

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
- 📊 **Request logging** — every request is recorded (endpoint, model, status,
  latency) in SQLite.
- 🧪 **Tested** — pytest suite covers auth, upstream client, Chat Completions,
  Responses, models, and health.
- 🚀 **Production-ready** — Gunicorn config + systemd unit file included.

---

## Quick Start

### 1. Clone and set up a virtual environment

```bash
cd /home/exedev/opengateway_ai_proxy
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
UPSTREAM_URL=https://opengateway.gitlawb.com/v1/chat/completions
UPSTREAM_API_KEY=                       # leave empty for guest mode
ADMIN_API_KEY=sk-quangdz-admin-ai       # change this in production
KEY_PREFIX=sk-quangdz
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
  -H "Authorization: Bearer sk-quangdz-admin-ai" \
  -H "Content-Type: application/json" \
  -d '{"uses": 100, "admin": 0}'
# {"key": "sk-quangdz-..."}
```

Use that key to call Chat Completions:

```bash
curl -X POST http://localhost/v1/chat/completions \
  -H "Authorization: Bearer sk-quangdz-..." \
  -H "Content-Type: application/json" \
  -d '{
    "model": "mimo-v2.5-pro",
    "messages": [{"role": "user", "content": "Hello!"}]
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

---

## Configuration (`.env`)

| Variable           | Default                                                       | Description                                                                                              |
| ------------------ | ------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------- |
| `UPSTREAM_URL`     | `https://opengateway.gitlawb.com/v1/chat/completions`         | Upstream Chat Completions endpoint.                                                                      |
| `UPSTREAM_API_KEY` | _(empty)_                                                     | Bearer token for upstream. Leave empty to use **guest mode** (proxy sends `Bearer guest`).               |
| `ADMIN_API_KEY`    | `sk-quangdz-admin-ai`                                         | Bootstrap admin key. Always treated as admin even if not in DB. **Change this in production.**           |
| `KEY_PREFIX`       | `sk-quangdz`                                                  | Prefix used when generating new API keys.                                                                |
| `DB_PATH`          | `api_keys.db`                                                 | Path to the SQLite database file.                                                                        |
| `LOG_LEVEL`        | `INFO`                                                        | Python logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`).                                              |
| `PORT`             | `80`                                                          | Port the dev server (`python main.py`) listens on. Gunicorn's port is controlled by `gunicorn.conf.py`. |

---

## Testing

The pytest suite mocks the upstream so no network calls are made.

```bash
source venv/bin/activate
pytest -v
```

Or run a specific test file:

```bash
pytest tests/test_chat.py -v
pytest tests/test_responses.py -v
```

Coverage spans:

- `tests/test_health.py` — `/health` endpoint
- `tests/test_auth.py` — auth middleware, API key CRUD, `/v1/status`
- `tests/test_upstream.py` — upstream client, error classification (mocked)
- `tests/test_chat.py` — `/v1/chat/completions` (non-stream, stream, tool calls,
  validation)
- `tests/test_responses.py` — `/v1/responses` (format conversion, streaming)
- `tests/test_models.py` — `/v1/models` and the model registry

---

## Deployment (systemd)

1. **Install the venv and dependencies** on the target host at
   `/home/exedev/opengateway_ai_proxy`:

   ```bash
   python3 -m venv venv
   venv/bin/pip install -r requirements.txt
   ```

2. **Create `.env`** in the project root (see _Configuration_ above).

3. **Install the systemd unit:**

   ```bash
   sudo cp opengateway-ai-proxy.service /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable --now opengateway-ai-proxy
   ```

4. **Inspect logs / status:**

   ```bash
   sudo systemctl status opengateway-ai-proxy
   sudo journalctl -u opengateway-ai-proxy -f
   ```

5. **Restart after code changes:**

   ```bash
   sudo systemctl restart opengateway-ai-proxy
   ```

The service runs as user `exedev` and uses `CAP_NET_BIND_SERVICE` to bind
port 80 without needing root.

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
  `db/`)
- Request flow for Chat Completions and Responses (streaming and non-streaming)
- Format-conversion rules between the Responses API and Chat Completions
- Database schema
- Key design decisions (passthrough philosophy, guest mode, hardcoded model list)

A brief sketch of the runtime flow:

```
Client ──POST /v1/chat/completions──▶ Auth middleware (API key + quota)
                                    ──▶ Validate model
                                    ──▶ upstream.client.call_upstream(...)
                                                 ──▶ https://opengateway.gitlawb.com/v1/chat/completions
                                    ◀── SSE chunks / JSON
                                    ──▶ (Responses API: convert chunk format)
                                    ──▶ Yield to client
                                    ──▶ After-request: log to SQLite
```

---

## License

Internal project. See repository owner for licensing details.
