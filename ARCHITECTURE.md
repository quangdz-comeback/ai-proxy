# Architecture — OpenGateway AI Proxy

## 1. Tổng quan

OpenGateway AI Proxy là một Flask gateway server export OpenAI-compatible API (`/v1/chat/completions` và `/v1/responses`), forward toàn bộ request lên upstream duy nhất:

```
https://opengateway.gitlawb.com/v1/chat/completions
```

Upstream hỗ trợ **native** full context + tool calling + streaming, nên proxy **không cần** emulate/simulate tool calling hay context distillation như base cũ.

### So sánh với base cũ (`/home/exedev/ai_proxy`)

| Khía cạnh | Base cũ (`ai_proxy`) | Mới (`opengateway_ai_proxy`) |
|---|---|---|
| Upstream | 3+ providers (MegaLLM, Airforce, DeepInfra, Ollama) | 1 upstream duy nhất (OpenGateway) |
| Tool calling | Emulate qua system prompt injection, parse XML/JSON response | Pass-through native upstream support |
| Context distillation | Có (`_distill_messages`, `_smart_shard`, `_DistillCache`) | Không cần — upstream nhận full context |
| Model routing | Fallback chain, sticky session, tier degradation | Passthrough — model name gửi nguyên bản lên upstream |
| Rate limiting | Per-upstream Semaphore + rate_gap | Global đơn giản (nếu cần) |
| Streaming | `_paced()` custom SSE pacing | Direct SSE passthrough từ upstream |
| Auth/API Keys | SQLite `api_keys` table + quota management | Giữ nguyên pattern từ base cũ |
| Responses API | Custom convert ↔ Chat Completions | Giữ pattern, đơn giản hơn vì upstream native support |
| Payload size limit | `_enforce_payload_size` + `_hard_trim_payload` | Không cần (upstream nhận full) |

## 2. System Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                        Client (OpenAI SDK)                       │
│  Continue.dev / Cursor / curl / custom client                    │
└──────────┬───────────────────────────────────┬───────────────────┘
           │                                   │
    POST /v1/chat/completions          POST /v1/responses
           │                                   │
           ▼                                   ▼
┌──────────────────────────────────────────────────────────────────┐
│                      Flask Application                           │
│                                                                  │
│  ┌─────────────────┐  ┌──────────────────┐  ┌────────────────┐  │
│  │  Auth Middleware │  │  Model Registry  │  │  Request Log   │  │
│  │  (API Key check)│  │  (resolve/alias) │  │  (SQLite)      │  │
│  └────────┬────────┘  └────────┬─────────┘  └───────┬────────┘  │
│           │                    │                     │           │
│  ┌────────▼────────────────────▼─────────────────────▼────────┐ │
│  │                    Endpoint Handlers                       │ │
│  │  /v1/chat/completions  →  chat()                          │ │
│  │  /v1/responses         →  responses_create()              │ │
│  │  /v1/models            →  models()                        │ │
│  │  /health               →  health()                        │ │
│  │  /v1/admin/*           →  admin CRUD                       │ │
│  └────────────────────────┬───────────────────────────────────┘ │
│                           │                                     │
│  ┌────────────────────────▼───────────────────────────────────┐ │
│  │              Upstream Client (requests)                    │ │
│  │  • Stream SSE passthrough                                  │ │
│  │  • Error handling & retry                                  │ │
│  │  • Response format adaptation                              │ │
│  └────────────────────────┬───────────────────────────────────┘ │
└───────────────────────────┼─────────────────────────────────────┘
                            │ HTTPS
                            ▼
         ┌──────────────────────────────────────┐
         │  opengateway.gitlawb.com             │
         │  /v1/chat/completions                │
         │  (Native tool calling + streaming)   │
         └──────────────────────────────────────┘
```

## 3. Module Structure

```
opengateway_ai_proxy/
├── app.py                  # Flask app factory, blueprint registration
├── config.py               # Configuration & env loading
├── main.py                 # CLI entrypoint (python main.py)
├── auth/
│   ├── __init__.py
│   ├── middleware.py        # API key auth, admin check, quota
│   └── api_keys.py         # DB operations for API key CRUD
├── upstream/
│   ├── __init__.py
│   ├── client.py           # Upstream HTTP client (stream/non-stream)
│   └── errors.py           # Upstream error classification
├── endpoints/
│   ├── __init__.py
│   ├── chat.py             # /v1/chat/completions handler
│   ├── responses.py        # /v1/responses handler
│   ├── models.py           # /v1/models handler
│   ├── health.py           # /health handler
│   └── admin.py            # /v1/admin/* handlers
├── models/
│   ├── __init__.py
│   └── registry.py         # Model name resolution, aliases
├── format/
│   ├── __init__.py
│   ├── responses_api.py    # Responses API ↔ Chat Completions conversion
│   └── sse.py              # SSE streaming helpers
├── db/
│   ├── __init__.py
│   ├── schema.sql          # SQLite schema
│   └── database.py         # DB connection, migrations
├── tests/
│   ├── test_chat.py        # Chat completions unit tests
│   ├── test_responses.py   # Responses API unit tests
│   ├── test_tools.py       # Tool calling passthrough tests
│   ├── test_auth.py        # Auth middleware tests
│   ├── test_models.py      # Model registry tests
│   ├── test_streaming.mjs  # Node.js streaming tests (OpenAI SDK)
│   └── test_continue.mjs   # Continue.dev compatibility tests
├── .env.example            # Environment template
├── requirements.txt
├── ARCHITECTURE.md
├── PLAN.md
└── README.md
```

## 4. Component Details

### 4.1 `config.py` — Configuration

Load từ `.env` file, cung cấp constants cho toàn app:

- `UPSTREAM_URL`: `https://opengateway.gitlawb.com/v1/chat/completions`
- `UPSTREAM_API_KEY`: API key cho upstream (nếu cần)
- `ADMIN_API_KEY`: Admin key cho proxy
- `KEY_PREFIX`: Prefix cho generated API keys (default: `sk-quangdz`)
- `DB_PATH`: Đường dẫn SQLite
- `RATE_LIMIT`: Cấu hình rate limiting

### 4.2 `auth/` — Authentication

**`middleware.py`**: Flask `before_request` hook:
- Parse `Authorization: Bearer <key>` header
- Validate key exists in DB
- Check quota (`uses > 0` hoặc `uses == -1` = unlimited)
- Set `g.api_key`, `g.is_admin`, `g.start_time`

**`api_keys.py`**: CRUD operations trên bảng `api_keys`:
- `create_key(uses, admin)` → generate key
- `get_key(key)` → return row
- `decrement_uses(key)` → trừ quota
- `list_keys()` / `edit_key()` / `delete_key()`

### 4.3 `upstream/` — Upstream Communication

**`client.py`**: Core upstream interaction:
- `call_upstream_stream(payload)`: Gửi request, return SSE generator passthrough
- `call_upstream_sync(payload)`: Gửi request non-stream, return parsed JSON
- Tự thêm `Authorization` header cho upstream nếu cần
- Error handling: timeout, connection refused, upstream 4xx/5xx

**`errors.py`**: Phân loại upstream errors:
- `UpstreamError`: Base exception
- `RateLimitError`: 429
- `AuthError`: 401/403
- `ModelError`: Invalid model name
- `ServerError`: 5xx

### 4.4 `endpoints/` — Flask Route Handlers

#### `chat.py` — `/v1/chat/completions`

**Non-streaming flow:**
1. Validate request body (model, messages)
2. Resolve model name
3. Forward payload lên upstream (stream=false)
4. Return upstream response nguyên bản

**Streaming flow:**
1. Validate request body
2. Resolve model name
3. Forward payload lên upstream (stream=true)
4. SSE passthrough — yield từng SSE chunk từ upstream trực tiếp về client
5. Inject `data: [DONE]` ở cuối stream

**Tool calling** (native passthrough):
- `tools`, `tool_choice`, `parallel_tool_calls` → forward nguyên bản
- `messages` với `role: "tool"` / `role: "assistant"` + `tool_calls` → forward nguyên bản
- Upstream xử lý hết, proxy chỉ pass-through

#### `responses.py` — `/v1/responses`

Responses API không phải upstream native format, nên cần conversion:

**Request conversion (Responses → Chat Completions):**
- `input` (string/array) → `messages`
- `instructions` → system message
- `tools` (Responses format) → `tools` (Chat Completions format)
- `tool_choice` mapping
- `max_output_tokens` → `max_tokens`
- Giữ nguyên `temperature`, `top_p`, etc.

**Response conversion — Non-streaming (Chat Completions → Responses):**
- Wrap response thành `output` array với `message` items
- Map `finish_reason` → `status`
- Map `tool_calls` → `function_call` output items

**Response conversion — Streaming:**
- Nhận SSE chunks từ upstream (Chat Completions format)
- Convert từng chunk thành Responses API events:
  - `response.created` / `response.in_progress` (initial)
  - `response.output_text.delta` (content chunks)
  - `response.output_text.done` (content complete)
  - `response.output_item.added` / `response.output_item.done` (tool calls)
  - `response.function_call_arguments.delta` / `.done`
  - `response.completed` (final)

#### `models.py` — `/v1/models`

- Return danh sách supported models
- Có thể hardcode hoặc fetch từ upstream `/v1/models` nếu có

#### `admin.py` — `/v1/admin/*`

Giữ nguyên CRUD pattern từ base cũ:
- `POST /v1/admin/api/create` — tạo API key
- `GET /v1/admin/api/list` — list keys
- `POST /v1/admin/api/edit` — sửa key
- `POST /v1/admin/api/delete` — xóa key
- `GET /v1/admin/logs` — xem request logs
- `GET /v1/status` — check key info

### 4.5 `models/registry.py` — Model Resolution

Đơn giản hơn base cũ vì chỉ có 1 upstream:

- Maintain danh sách models upstream hỗ trợ
- Alias resolution: `gpt-5.3-codex` → `gpt-5.3-codex` (passthrough)
- Có thể map dotted names nếu cần: `newclaude-opus-4.6` → `newclaude-opus-4-6`
- Validation: reject model name rỗng hoặc không hợp lệ

### 4.6 `format/` — Format Conversion

**`responses_api.py`**: Conversion helpers giữa 2 API formats:
- `responses_input_to_messages(body)` — convert Responses input → messages array
- `build_response_object(...)` — build non-streaming Responses object
- `build_stream_event(...)` — build individual SSE event
- `convert_stream_chunk(chunk)` — convert Chat Completions chunk → Responses events

**`sse.py`**: SSE utilities:
- `sse_response(generator)` — Flask Response wrapper cho SSE
- `parse_sse_stream(response)` — parse upstream SSE vào Python generator

### 4.7 `db/` — Database

SQLite, schema tương tự base cũ:

```sql
CREATE TABLE api_keys (
    key TEXT PRIMARY KEY,
    uses INTEGER DEFAULT -1,
    admin INTEGER DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE request_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    api_key TEXT,
    endpoint TEXT,
    model TEXT,
    stream INTEGER,
    status INTEGER,
    latency_ms INTEGER,
    error TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
```

## 5. Data Flow

### 5.1 Chat Completions (streaming)

```
Client POST /v1/chat/completions {stream: true}
  │
  ├─ Auth middleware validates API key
  ├─ Resolve model name
  │
  ▼
upstream_client.call_upstream_stream(payload)
  │
  ├─ POST https://opengateway.gitlawb.com/v1/chat/completions
  ├─ Read SSE chunks from response.iter_lines()
  ├─ Yield each chunk directly to client
  │
  ▼
Client receives SSE stream (OpenAI format)
  │
  ├─ After_request: log request to DB
```

### 5.2 Responses API (streaming)

```
Client POST /v1/responses {stream: true}
  │
  ├─ Auth middleware validates API key
  ├─ Convert Responses input → Chat Completions messages
  ├─ Convert Responses tools → Chat Completions tools
  │
  ▼
upstream_client.call_upstream_stream(payload)
  │
  ├─ POST upstream with stream=true
  ├─ Read SSE chunks
  ├─ For each chunk: convert to Responses API events
  │   ├─ content delta → response.output_text.delta
  │   ├─ tool_calls delta → response.output_item.added + function_call_arguments.delta
  │   ├─ finish_reason → response.completed
  │
  ▼
Client receives SSE stream (Responses API format)
```

## 6. Key Design Decisions

1. **Single upstream, passthrough**: Không cần multi-provider routing, fallback chains, hay sticky sessions. Đơn giản và reliable.

2. **Native tool calling**: Không inject system prompts hay parse response text. Upstream xử lý tool calling native, proxy chỉ forward.

3. **No context distillation**: Upstream accept full context, không cần shard/summarize.

4. **Modular structure**: Tách thành modules rõ ràng thay vì 1 file 3400 dòng như base cũ. Dễ test, dễ maintain.

5. **Responses API conversion**: Layer chuyển đổi giữa Responses format và Chat Completions format, vì upstream chỉ nói Chat Completions.

6. **Auth & quota giữ nguyên pattern**: SQLite-based API key management giống base cũ, tested và stable.

7. **Test suite**: Kế thừa pattern test từ base cũ — Python unit tests (pytest) + Node.js integration tests (OpenAI SDK).