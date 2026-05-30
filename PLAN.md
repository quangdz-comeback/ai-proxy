# Implementation Plan — OpenGateway AI Proxy

## Tổng quan

Flask gateway export OpenAI-compatible API, forward lên upstream duy nhất
`https://opengateway.gitlawb.com/v1/chat/completions`. Hỗ trợ Budget Mode —
auto cache + tool call compression triggered by `reasoning_effort="budget"`.

---

## Completed Phases

### Phase 0: Project Bootstrap ✅
- Git repo, `requirements.txt`, `.env.example`, `.gitignore`

### Phase 1: Core Infrastructure ✅
- `config.py`, `db/`, `app.py`, `main.py`, health endpoint

### Phase 2: Authentication & Admin ✅
- API key auth middleware, CRUD endpoints, quota management
- Admin key bootstrap from env (`ADMIN_API_KEY`)
- `uses=NULL` means unlimited, negative normalized to NULL

### Phase 3: Upstream Client ✅
- `upstream/client.py` — HTTP client with gzip-safe response handling
- `upstream/errors.py` — Error classification hierarchy
- **Bug fix**: Upstream sends `Content-Encoding: gzip` but plain body → fixed
  with gzip magic byte (`\x1f\x8b`) check in `_safe_read_response()`

### Phase 4: Chat Completions Endpoint ✅
- `endpoints/chat.py` — stream + non-stream passthrough
- `models/registry.py` — 5 hardcoded mimo models
- `format/sse.py` — SSE response helpers

### Phase 5: Responses API Endpoint ✅
- `format/responses_api.py` — Conversion between Responses API ↔ Chat Completions
- `endpoints/responses.py` — stream + non-stream with format conversion
- `ResponseStreamConverter` class for streaming

### Phase 6: Models + Usage + Admin Management ✅
- `GET /v1/models` (no auth), `GET /v1/usage` (markdown API docs)
- Full `/v1/admin/*` management: create (201), list, edit, delete, logs with filters
- Params from query string or JSON body

### Phase 7: Deployment + DB Migration ✅
- `gunicorn.conf.py` (bind 0.0.0.0:80, 1 worker, gthread, 4 threads, timeout 120)
- `opengateway-ai-proxy.service` systemd unit file
- **DB migration**: `init_db()` auto-migrates old schemas via `ALTER TABLE`
  (adds `name` column to `api_keys`, `ts` column to `request_log`)

### Phase 8: Budget Mode — Auto Cache + Tool Call Compression ✅
- Commit: `7211db8` — 20 files, +2469 lines
- **Trigger**: `reasoning_effort="budget"` activates compression pipeline
- **Caveman prompt**: terse response style injected into system prompt
- **Tool output compression**: rule-based per tool type (ls→filenames,
  grep→summary, npm/pip→summary, generic→truncate middle)
- **Debug noise**: LLM (mimo-v2-flash) summarizes noisy debug lines
- **History compression**: LLM summarizes old turns, keeps focal points
  (files, git state, core logic, changelogs, state tracking)
- **Error dedup with migration**: same error at multiple locations merged
  into single block with all locations (no silent drops)
- **LRU cache**: thread-safe, per-key isolation, TTL, delta support
- 67 new tests (153 total)

---

## Git Log

```
7211db8 Add budget mode: auto cache + tool call compression system
aa5db93 fix: add DB migration for old schema (name column, ts column)
cd9de3c feat: add /v1/usage docs + full admin management matching base project
92b6729 fix: handle upstream gzip encoding mismatch with magic byte check
f66aaa1 Implement OpenGateway AI Proxy per ARCHITECTURE.md/PLAN.md
3ea92ee Phase 1: Core infrastructure — config, DB, health endpoint
1ca4ed9 Update architecture & plan: hardcoded mimo models, guest mode fallback
75c0ce6 Initial project bootstrap: ARCHITECTURE.md, PLAN.md, requirements, .gitignore
```

---

## Future Considerations

- Deploy budget mode to container at `/home/container/`
- Add Prometheus metrics for cache hit rates, compression ratios
- Add `/v1/admin/cache` endpoint for cache inspection/clearing
- Consider persistent cache (Redis/file-backed) for multi-worker gunicorn
- Add compression ratio stats to request_log
