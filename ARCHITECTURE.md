# Architecture — OpenGateway AI Proxy

## 1. Tổng quan

Flask gateway export OpenAI-compatible API (`/v1/chat/completions`, `/v1/responses`),
forward lên upstream duy nhất:

```
UPSTREAM_URL (configured in .env)
```

Upstream hỗ trợ native tool calling + streaming. Proxy passthrough, không emulate.

**Budget Mode** (`reasoning_effort="budget"`): auto cache + tool call compression
pipeline — compress tool outputs, summarize debug noise, deduplicate errors,
summarize old history, inject terse "caveman" system prompt.

## 2. System Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                       Client (OpenAI SDK)                           │
│   Continue.dev / Cursor / curl / custom client                     │
└──────────┬───────────────────────────────────┬──────────────────────┘
           │                                   │
    POST /v1/chat/completions          POST /v1/responses
           │                                   │
           ▼                                   ▼
┌─────────────────────────────────────────────────────────────────────┐
│                       Flask Application                             │
│                                                                     │
│  ┌─────────────────┐  ┌──────────────────┐  ┌────────────────────┐  │
│  │  Auth Middleware │  │  Model Registry  │  │  Request Log       │  │
│  │  (API Key check)│  │  (5 mimo models) │  │  (SQLite)          │  │
│  └────────┬────────┘  └────────┬─────────┘  └───────┬────────────┘  │
│           │                    │                     │               │
│  ┌────────▼────────────────────▼─────────────────────▼────────────┐ │
│  │                    Endpoint Handlers                          │ │
│  │  /v1/chat/completions  →  chat()                             │ │
│  │  /v1/responses         →  responses_create()                 │ │
│  │  /v1/models            →  models()          [no auth]       │ │
│  │  /health, /v1/health   →  health()           [no auth]       │ │
│  │  /v1/usage             →  usage()            [no auth]       │ │
│  │  /v1/admin/*           →  admin CRUD         [admin only]    │ │
│  └────────────────────────┬────────────────────────────────────────┘ │
│                           │                                         │
│  ┌────────────────────────▼────────────────────────────────────────┐ │
│  │            Budget Compression Pipeline                        │ │
│  │  (activated when reasoning_effort="budget")                   │ │
│  │                                                               │ │
│  │  1. Inject caveman system prompt                              │ │
│  │  2. compress/history.py    — LLM summarize old turns          │ │
│  │  3. compress/tool_output.py — rule-based per-tool compress    │ │
│  │     cache/lru_store.py     — LRU cache with delta support     │ │
│  │  4. compress/debug_noise.py — LLM summarize noisy lines      │ │
│  │  5. compress/dedup.py      — error migration + line dedup    │ │
│  │  6. Strip reasoning_effort, forward to upstream               │ │
│  └────────────────────────┬────────────────────────────────────────┘ │
│                           │                                         │
│  ┌────────────────────────▼────────────────────────────────────────┐ │
│  │              Upstream Client (requests)                       │ │
│  │  • Gzip-safe response handling (magic byte check)             │ │
│  │  • SSE stream passthrough                                     │ │
│  │  • Error classification → UpstreamError hierarchy             │ │
│  └────────────────────────┬────────────────────────────────────────┘ │
└───────────────────────────┼─────────────────────────────────────────┘
                            │ HTTPS
                            ▼
         ┌──────────────────────────────────────┐
         │  UPSTREAM_URL                         │
         │  /v1/chat/completions                │
         │  (Native tool calling + streaming)   │
         └──────────────────────────────────────┘
```

## 3. Module Structure

```
opengateway_ai_proxy/
├── app.py                    # Flask app factory, blueprint registration
├── config.py                 # Config + env loading (incl. budget settings)
├── main.py                   # CLI entrypoint
│
├── auth/
│   ├── middleware.py          # before_request auth + after_request logging
│   └── api_keys.py           # DB ops: CRUD, quota, logging
│
├── upstream/
│   ├── client.py             # Upstream HTTP client (gzip-safe)
│   └── errors.py             # Error classification hierarchy
│
├── endpoints/
│   ├── chat.py               # /v1/chat/completions + budget integration
│   ├── responses.py          # /v1/responses + budget integration
│   ├── models.py             # /v1/models (no auth)
│   ├── health.py             # /health, /v1/health
│   ├── usage.py              # /v1/usage (markdown API docs, no auth)
│   └── admin.py              # /v1/admin/* CRUD + logs
│
├── models/
│   └── registry.py           # 5 hardcoded mimo models
│
├── format/
│   ├── responses_api.py      # Responses API ↔ Chat Completions conversion
│   └── sse.py                # SSE streaming helpers
│
├── db/
│   ├── schema.sql            # SQLite schema
│   └── database.py           # DB connection + auto-migration
│
├── budget/                    # Budget mode orchestration
│   ├── trigger.py            # Detect reasoning_effort="budget"
│   └── pipeline.py           # Coordinate all compression modules
│
├── cache/                     # Caching infrastructure
│   ├── lru_store.py          # Thread-safe LRU cache (TTL, per-key isolation)
│   └── delta.py              # Unified diff delta engine
│
├── compress/                  # Compression modules
│   ├── markers.py            # Constants + Caveman system prompt
│   ├── llm.py                # LLM wrapper (mimo-v2-flash via upstream)
│   ├── tool_output.py        # Rule-based tool output compression
│   ├── debug_noise.py        # LLM noise summarization
│   ├── history.py            # LLM history focal point extraction
│   └── dedup.py              # Error migration + line deduplication
│
├── tests/                     # 153 tests, all passing
│   ├── conftest.py           # Fixtures: app, client, admin_key, user_key
│   ├── helpers.py            # make_mock_response() helper
│   ├── test_auth.py
│   ├── test_budget_pipeline.py
│   ├── test_budget_trigger.py
│   ├── test_cache.py
│   ├── test_chat.py
│   ├── test_compress_dedup.py
│   ├── test_compress_history.py
│   ├── test_compress_noise.py
│   ├── test_compress_tool.py
│   ├── test_health.py
│   ├── test_models.py
│   ├── test_responses.py
│   ├── test_upstream.py
│   └── test_usage_admin.py
│
├── gunicorn.conf.py          # Production: 0.0.0.0:80, gthread, 4 threads
├── opengateway-ai-proxy.service  # Systemd unit
├── requirements.txt
├── .env.example
├── ARCHITECTURE.md
└── PLAN.md
```

## 4. Component Details

### 4.1 `config.py` — Configuration

Load từ `.env`, constants:

| Variable | Default | Purpose |
|----------|---------|----------|
| `UPSTREAM_URL` | `http://localhost:11434/v1/chat/completions` | Upstream endpoint |
| `UPSTREAM_API_KEY` | `""` | Upstream auth (empty = guest mode) |
| `ADMIN_API_KEY` | _(empty — must be set)_ | Admin key for proxy |
| `KEY_PREFIX` | `sk-proxy` | Prefix for generated API keys |
| `DB_PATH` | `api_keys.db` | SQLite database path |
| `PORT` | `80` | Server port |
| `BUDGET_ENABLED` | `true` | Enable/disable budget mode |
| `BUDGET_CACHE_SIZE` | `256` | LRU cache max entries |
| `BUDGET_CACHE_TTL` | `3600` | Cache entry TTL (seconds) |
| `BUDGET_HISTORY_KEEP_N` | `4` | Recent messages to keep uncompressed |
| `BUDGET_COMPRESS_THRESHOLD` | `500` | Min chars to trigger tool output compression |

`get_upstream_auth()`: Returns `UPSTREAM_API_KEY` if set, else `"guest"`.

### 4.2 `auth/` — Authentication & Authorization

**`middleware.py`** — `init_auth(app)`:
- `before_request`: Parse `Authorization: Bearer <key>`, validate, check quota
  - Skip auth for `/health`, `/v1/health`, `/v1/models`, `/v1/usage`
  - Admin bootstrap: `g.api_key == ADMIN_API_KEY` from env → `g.is_admin = True`
  - Quota: `uses=NULL` = unlimited, `uses<=0` = exhausted → 429
  - Skip quota decrement for `/v1/status` and `/v1/admin/*`
- `after_request`: Log request to `request_log` table

**`api_keys.py`**: CRUD operations
- `create_key(name, uses, admin)` — `uses=None` or negative = unlimited
- `get_key()`, `list_keys()`, `edit_key()`, `delete_key()`
- `decrement_uses()`, `log_request()`, `get_logs(filters)`
- `name` column is UNIQUE

### 4.3 `upstream/` — Upstream Communication

**`client.py`**:
- `call_upstream(payload, stream, timeout)`: Always `stream=True` in requests
  to bypass auto gzip decoding. Handles gzip via magic byte check (`\x1f\x8b`).
- `_safe_read_response(resp)`: Read raw bytes, check magic bytes before
  gzip decompression. Handles upstream sending `Content-Encoding: gzip`
  header with uncompressed body.
- `iter_sse_lines(resp)`: SSE line iterator with same gzip-safe handling.
- Returns: parsed JSON dict (non-stream) or raw Response (stream).

**`errors.py`** — Exception hierarchy:
- `UpstreamError` (base) → `RateLimitError` (429), `AuthError` (401/403),
  `ModelNotFoundError` (404), `ServerError` (5xx)
- `classify_error(resp)` raises (not returns) the appropriate exception

### 4.4 `endpoints/` — Route Handlers

**`chat.py`** — `/v1/chat/completions`:
- Validate body (model, messages required)
- Resolve model, apply budget compression if triggered
- Stream/non-stream passthrough using `iter_sse_lines`

**`responses.py`** — `/v1/responses`:
- Convert Responses API → Chat Completions format
- Apply budget compression if triggered
- Stream/non-stream using `iter_sse_lines`
- Convert response back to Responses API format

**`models.py`** — `/v1/models` (no auth): Hardcoded 5 mimo models

**`health.py`** — `/health`, `/v1/health`: `{"status": "ok"}`

**`usage.py`** — `/v1/usage` (no auth): Markdown API documentation

**`admin.py`** — `/v1/admin/*`:
- `POST /v1/admin/api/create` (returns 201)
- `GET /v1/admin/api/list`
- `POST|PATCH|PUT /v1/admin/api/edit`
- `POST|DELETE /v1/admin/api/delete` (by key or name)
- `GET /v1/admin/logs` (with `?limit=N&key=XXX` filters)

### 4.5 `models/registry.py` — Hardcoded Models

5 mimo models: `mimo-v2.5-pro`, `mimo-v2.5`, `mimo-v2-pro`,
`mimo-v2-flash`, `mimo-v2-omni`. `resolve_model()` validates, `get_model_list()`
returns OpenAI-format list. Upstream has no `/v1/models` endpoint.

### 4.6 `format/` — Format Conversion

**`responses_api.py`** (395 lines):
- `responses_input_to_messages(body)` — input → messages (handles items with
  `role` but no `type`, content as string or array of parts)
- `responses_tools_to_cc_tools(tools)` — tool format conversion
- `build_response_object(...)` — non-streaming response
- `ResponseStreamConverter` class — stateful streaming converter with
  accumulators for text and tool calls across chunks

**`sse.py`**: `sse_response(generator)` — Flask Response wrapper for SSE

### 4.7 `db/` — Database

SQLite schema:
```sql
CREATE TABLE api_keys (
    key TEXT PRIMARY KEY,
    name TEXT UNIQUE,
    uses INTEGER,        -- NULL = unlimited
    admin INTEGER DEFAULT 0,
    created_at INTEGER   -- epoch
);
CREATE TABLE request_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL,             -- epoch
    api_key TEXT,
    endpoint TEXT,
    model TEXT,
    stream INTEGER,
    status INTEGER,
    latency_ms INTEGER,
    error TEXT
);
```

`database.py` — `init_db()`: Auto-migrates old schemas via `ALTER TABLE`
(detects missing `name`/`ts` columns, adds them, backfills data).

### 4.8 `budget/` — Budget Mode Orchestration

**`trigger.py`**:
- `is_budget_mode(payload) → bool` — checks `payload.get("reasoning_effort") == "budget"`
- Custom value not recognized by upstream — proxy intercepts and strips it

**`pipeline.py`** — `transform_payload(payload, api_key) → dict`:
1. Early return if not budget mode (zero overhead)
2. Inject caveman system prompt
3. `compress_history()` — summarize old turns, keep last N + focal points
4. Walk messages, compress per-type:
   - `role=tool` → `compress_tool_output()` (rule-based + LRU cache)
   - `role=assistant` → `compress_debug_noise()` + `deduplicate_lines()`
   - `role=user` → `deduplicate_lines()`
5. Strip `reasoning_effort` field
6. Fail-open: on any exception, log warning, use original payload

### 4.9 `cache/` — Caching Infrastructure

**`lru_store.py`** — `BudgetLRUCache`:
- Thread-safe (`threading.Lock`) LRU cache wrapping `OrderedDict`
- `CacheEntry` dataclass: `compressed_output`, `raw_hash`, `timestamp`
- TTL expiration (checked on get, batch cleanup on put when >80% capacity)
- Per-API-key isolation via composite keys: `f"{api_key}:{tool_name}:{hash}"`
- Singleton `get_cache()` with lazy initialization from config

**`delta.py`**:
- `compute_delta(old, new) → str | None` — unified diff, None if delta ≥ 70%
  of new text size (not worthwhile)
- `apply_delta(base, delta) → str | None` — reverse apply, None on failure
- `is_delta_worthwhile(new_len, delta_len) → bool`

### 4.10 `compress/` — Compression Modules

**`markers.py`** — Constants:
- `BUDGET_CACHE_PREFIX` / `BUDGET_CACHE_SUFFIX` — cache item markers
- `BUDGET_HISTORY_PREFIX` — history summary marker
- `BUDGET_DEDUP_PREFIX` — dedup summary marker
- `CAVEMAN_PROMPT` — full caveman system prompt (terse response style)

**`llm.py`** — `compress_with_llm(system_prompt, content, max_tokens=300)`:
- Calls upstream via `call_upstream()` with `mimo-v2-flash` model
- Used by `debug_noise.py` and `history.py` for LLM-based summarization
- Low temperature (0.3) for deterministic-ish output

**`tool_output.py`** — `compress_tool_output(tool_name, output, api_key)`:
- Rule-based compressors (NO LLM) per tool type:
  - `ls`/`find`/`tree`: keep filenames only, truncate >50 entries
  - `cat`/`head`/`tail`: keep verbatim
  - `grep`/`rg`: summarize if >50 matches
  - `npm`/`pip`/`apt` install: keep summary line only
  - `pytest`/`jest`: keep pass/fail summary
  - `git`/`docker`/`kubectl`: keep verbatim
  - Generic: truncate middle if >2000 chars
- Short output (<500 chars) → unchanged
- LRU cache: hash raw → check cache → delta or full compress → store
- Cache marker format: `[BUDGET_CACHE:tool=ls:hash=abc123:mode=full]`

**`debug_noise.py`** — `compress_debug_noise(text)`:
- Classify lines: KEEP (errors, warnings, code blocks) vs NOISE (DEBUG, TRACE,
  progress bars, ANSI codes, stack frames >5, verbose INFO)
- <3 noise lines → unchanged
- ≥3 noise lines → call LLM to summarize into 1-2 lines
- Reassemble: KEEP lines + `[BUDGET_NOISE_SUMMARY] {summary}`
- Fail-open on LLM errors

**`history.py`** — `compress_history(messages, keep_last_n=4, api_key="")`:
- ≤ keep_last_n + 1 messages → unchanged
- Old turns: extract state messages (completed/TODO/pending) → preserve verbatim
- Summarize remaining old turns via LLM: [FILES] [GIT] [LOGIC] [CHANGELOG] [STATE]
- Output: state messages + `[BUDGET_HISTORY] {summary}` + recent turns
- Fail-open on LLM errors

**`dedup.py`** — `deduplicate_lines(text)`:
- Phase 1: Classify each line (error/warning/traceback/info/code_fence/other)
- Phase 2: Extract template — strip varying parts (line numbers, IPs, timestamps,
  file paths, memory addresses) → normalized template + extracted fields
- Phase 3: Merge consecutive same-template errors into compact representation:
  - Single field, short values → inline: `"Error at lines 10, 25, 42"`
  - Multiple fields or long values → block with indented list
  - >10 occurrences → summary with first 3 + last 2
  - Tracebacks → keep unique frames, note total count
- Code fences preserved verbatim
- Info/other lines: simple exact dedup
- **Critical rule**: every error/warning occurrence MUST have representation.
  Counts are never silently dropped.
- Trailer: `[BUDGET_DEDUP: N duplicate info lines removed]`

## 5. Data Flow

### 5.1 Chat Completions with Budget Mode

```
Client POST /v1/chat/completions {model, messages, reasoning_effort: "budget"}
  │
  ├─ Auth middleware validates API key
  ├─ Resolve model name
  │
  ├─ is_budget_mode(payload) → true
  │   ├─ Inject caveman system prompt
  │   ├─ compress_history() → summarize old turns
  │   ├─ For tool messages: compress_tool_output() (rule-based + cache)
  │   ├─ For assistant messages: compress_debug_noise() + deduplicate_lines()
  │   ├─ For user messages: deduplicate_lines()
  │   └─ Strip reasoning_effort field
  │
  ▼
call_upstream(transformed_payload, stream)
  │
  ├─ POST UPSTREAM_URL
  ├─ Gzip-safe response handling
  ├─ SSE passthrough (stream) or JSON parse (non-stream)
  │
  ▼
Client receives response (unchanged from upstream)
  │
  ├─ After_request: log request to DB
```

### 5.2 Responses API (streaming)

```
Client POST /v1/responses {stream: true}
  │
  ├─ Convert input → messages, tools → CC tools
  ├─ Apply budget compression if triggered
  │
  ▼
call_upstream(cc_payload, stream=true)
  │
  ├─ Read SSE chunks via iter_sse_lines()
  ├─ ResponseStreamConverter converts each chunk → Responses events
  │   ├─ content delta → response.output_text.delta
  │   ├─ tool_calls → response.output_item.added + function_call_arguments.delta
  │   └─ finish_reason → response.completed
  │
  ▼
Client receives SSE stream (Responses API format)
```

## 6. Key Design Decisions

1. **Single upstream, passthrough**: No multi-provider routing, fallback chains,
   or sticky sessions. Simple and reliable.

2. **Guest mode fallback**: If `UPSTREAM_API_KEY` is empty, send `Bearer guest`.

3. **Gzip-safe response handling**: Upstream claims `Content-Encoding: gzip`
   but may send plain body. Fixed with magic byte check before decompression.

4. **Native tool calling**: No system prompt injection or response parsing.
   Upstream handles natively, proxy forwards.

5. **Budget mode trigger**: Uses `reasoning_effort="budget"` — a custom value
   not in OpenAI spec. Proxy intercepts, strips before forwarding upstream.
   Non-budget requests have zero overhead (early return in transform_payload).

6. **Budget compression uses mimo-v2-flash**: Fast model for LLM-based
   summarization (debug noise, history). Tool output compression is rule-based
   (no LLM needed). Pipeline fails open — never breaks requests on errors.

7. **Error dedup with migration**: Same error at multiple locations merged into
   a single block preserving ALL locations. No silent drops of error counts.

8. **Thread-safe LRU cache**: Per-API-key isolation, TTL expiration, delta
   support for incremental tool output changes.

9. **DB auto-migration**: `init_db()` detects old schemas, runs ALTER TABLE
   for missing columns, backfills data. Handles container DBs from older versions.

10. **Schema differences from base project**: `api_keys` has `name TEXT UNIQUE`,
    `uses INTEGER NULL` (NULL=unlimited vs old -1), `created_at INTEGER` (epoch
    vs old TEXT). `request_log` has `ts REAL` + indexes.

## 7. Key Facts for Context Restoration

- **Project path**: Deploy anywhere (clone repo, set up venv)
- **Upstream URL**: Configured via `UPSTREAM_URL` env var
- **Real upstream API key**: Stored in `.env` (never hardcode)
- **Key prefix**: Configured via `KEY_PREFIX` env var (default `sk-proxy`)
- **DB**: SQLite at `DB_PATH` (default `api_keys.db`)
- **Deployment**: Container at `/home/container/` — copy files, run `python main.py`
- **Requirements**: flask, requests, gunicorn, python-dotenv
- **Python**: 3.12 (dev), 3.14 (container)
- **Tests**: 153 passing (86 original + 67 budget mode)
- **Total lines**: ~5830 across all Python files

### Critical Gotchas
- `requests.Response.iter_content()` does NOT have `decode_content` param (that's urllib3)
- Must use `resp.raw.read()` to bypass requests' auto gzip decoding
- SQLite `CREATE TABLE IF NOT EXISTS` won't alter existing tables — need ALTER TABLE migration
- `classify_error()` raises exceptions, doesn't return them
- Admin key bootstrap from env, not just DB lookup
- `uses=NULL` means unlimited; negative values normalized to NULL in `create_key()`
- Budget LLM calls go through `call_upstream()` — must not trigger recursive budget pipeline
- Budget pipeline only touches request payload, never touches response