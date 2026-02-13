# Grub Crawler

The world's only agentic web crawler. Built using the brain of a human that knows about distributed crawling architectures. A dual-mode crawling service that operates as both a traditional API tool and an autonomous agent capable of multi-step browsing, extraction, and reasoning over live web content.

## Overview

Grub Crawler goes beyond fetch-and-parse. It combines a production-grade crawling API with a bounded internal agent loop that can plan, execute, and observe across multiple pages autonomously — all under strict policy controls, typed error contracts, and replayable traces.

- **Mode A (External)** - First-class tool endpoints for agents and orchestrators
- **Mode B (Internal)** - Opt-in autonomous agent loop with LLM-driven planning
- **Ghost Protocol** - Vision-based fallback: when anti-bot blocks DOM scraping, screenshots the page and extracts content via Claude/GPT-4o vision
- **Live Browser Stream** - Real-time viewport streaming over WebSocket/MJPEG (planned)
- **Multi-provider LLM** - OpenAI, Anthropic, and Ollama with automatic fallback rotation
- **Policy-gated execution** - Domain allowlists, private-range deny, secret redaction
- **Replayable traces** - Every agent run produces a JSON trace for debugging and replay
- **User partitioned storage** - Secure, isolated data per customer (local or GCS)

## API Endpoints

### Core Crawling
| Method | Path | Description | Status |
|--------|------|-------------|--------|
| `POST` | `/api/crawl` | Single URL crawl (HTML + markdown) | Live |
| `POST` | `/api/markdown` | Single or multi-URL markdown extraction | Live |
| `POST` | `/api/batch` | Batch crawl with job tracking | Live |
| `POST` | `/api/raw` | Raw HTML extraction (no markdown) | Live |
| `GET`  | `/view` | Browser-rendered HTML viewer | Live |
| `GET`  | `/download` | File download (PDFs, etc.) through crawler | Live |

### Agent (Mode B)
| Method | Path | Description | Status |
|--------|------|-------------|--------|
| `POST` | `/api/agent/run` | Submit task to autonomous agent loop | Live |
| `GET`  | `/api/agent/status/{run_id}` | Check agent run status / load trace | Live |
| `POST` | `/api/agent/ghost` | Ghost Protocol: screenshot + vision extract | Live |

### Job Management
| Method | Path | Description | Status |
|--------|------|-------------|--------|
| `POST` | `/api/jobs/create` | Generic job submission | Live |
| `POST` | `/api/jobs/crawl` | Submit single URL crawl job | Live |
| `POST` | `/api/jobs/batch-crawl` | Submit batch crawl job | Live |
| `POST` | `/api/jobs/markdown` | Submit markdown-only job | Live |
| `POST` | `/api/jobs/process-job` | Cloud Tasks worker endpoint | Live |
| `POST` | `/api/wraith` | AI-driven crawl workflow | Placeholder |

### Remote Cache
| Method | Path | Description | Status |
|--------|------|-------------|--------|
| `POST` | `/api/cache/search` | Fuzzy search cached content | Live |
| `GET`  | `/api/cache/list` | List cached document metadata | Live |
| `GET`  | `/api/cache/doc/{doc_id}` | Fetch one cached document | Live |
| `POST` | `/api/cache/upsert` | Upsert cache entries | Live |
| `POST` | `/api/cache/prune` | Prune cache entries by TTL/domain | Live |

### Session Management
| Method | Path | Description | Status |
|--------|------|-------------|--------|
| `GET`  | `/api/sessions/{session_id}/files` | List session files | Live |
| `GET`  | `/api/sessions/{session_id}/file` | Get specific file | Live |
| `GET`  | `/api/sessions/{session_id}/status` | Session progress status | Live |
| `GET`  | `/api/sessions/{session_id}/results` | All crawl results | Live |
| `GET`  | `/api/sessions/{session_id}/screenshots` | List screenshots | Live |

### Live Stream (Planned)
| Method | Path | Description | Status |
|--------|------|-------------|--------|
| `WS`   | `/stream/{session_id}` | WebSocket viewport stream | Planned |
| `GET`  | `/stream/{session_id}/mjpeg` | MJPEG fallback stream | Planned |

### System
| Method | Path | Description | Status |
|--------|------|-------------|--------|
| `GET`  | `/health` | Health check + tool count | Live |
| `GET`  | `/tools` | List registered AHP tools | Live |
| `GET`  | `/{tool_name}` | Execute AHP tool (catch-all) | Live |

## MCP Tools (grub-crawl.py)

The MCP bridge exposes all capabilities to any MCP-compatible host:

| Tool | Description | Status |
|------|-------------|--------|
| `crawl_url` | Single URL markdown extraction with JS injection | Live |
| `crawl_batch` | Batch processing up to 50 URLs with collation | Live |
| `raw_html` | Raw HTML fetch without conversion | Live |
| `download_file` | Download files (PDFs, etc.) through crawler | Live |
| `crawl_validate` | Content quality assessment | Live |
| `crawl_search` | Fuzzy search local crawl cache | Live |
| `crawl_cache_list` | List local cached files | Live |
| `crawl_remote_search` | Search remote crawler cache | Live |
| `crawl_remote_cache_list` | List remote cache entries | Live |
| `crawl_remote_cache_doc` | Fetch remote cached document | Live |
| `agent_run` | Submit task to autonomous agent (Mode B) | Live |
| `agent_status` | Check agent run status | Live |
| `ghost_extract` | Ghost Protocol: screenshot + vision AI extraction | Live |
| `set_auth_token` | Save auth token to .wraithenv | Live |
| `crawl_status` | Report configuration and connection | Live |

## Internal Modules

### Agent Core (`app/agent/`)
| File | Purpose | Status |
|------|---------|--------|
| `types.py` | `RunState` enum, `StopReason`, `ToolCall`, `ToolResult`, `AssistantAction`, `RunConfig`, `RunContext`, `StepTrace`, `RunResult` | Done |
| `errors.py` | Typed errors: `validation_error`, `policy_denied`, `tool_timeout`, `tool_unavailable`, `execution_error`, `provider_error`, `stop_condition` | Done |
| `dispatcher.py` | Tool validation, timeout enforcement (30s), retry (1x), typed error normalization | Done |
| `engine.py` | Bounded loop: `plan -> execute -> observe -> stop`. EventBus integration. Returns `(RunResult, RunSummary)` | Done |
| `ghost.py` | Ghost Protocol: block detection, screenshot capture, vision extraction, auto-trigger | Done |

### Provider Adapters (`app/agent/providers/`)
| File | Purpose | Status |
|------|---------|--------|
| `base.py` | `LLMAdapter` ABC, `FallbackAdapter` (rotate on failure), factory functions | Done |
| `openai_adapter.py` | OpenAI tool_calls mapping, GPT-4o vision | Done |
| `anthropic_adapter.py` | Anthropic tool_use/tool_result blocks, Claude Sonnet vision | Done |
| `ollama_adapter.py` | Ollama HTTP `/api/chat`, llava vision | Done |

### Policy Gates (`app/policy/`)
| File | Purpose | Status |
|------|---------|--------|
| `domain.py` | Domain allowlist, RFC-1918/loopback/link-local deny | Done |
| `gate.py` | Pre-tool and pre-fetch policy checks with `PolicyVerdict` | Done |
| `redaction.py` | Secret pattern redaction (API keys, JWTs, private keys) | Done |

### Observability (`app/observability/`)
| File | Purpose | Status |
|------|---------|--------|
| `events.py` | `EventBus` + 7 typed events: `run_start`, `step_start`, `tool_dispatch`, `tool_result`, `policy_denied`, `step_end`, `run_end` | Done |
| `trace.py` | `TraceCollector`, `RunSummary` JSON serialization, `persist_trace()` / `load_trace()` via storage | Done |

### API Layer
| File | Purpose | Status |
|------|---------|--------|
| `agent_routes.py` | `POST /api/agent/run`, `GET /api/agent/status/{run_id}`. 503 when disabled | Done |
| `routes.py` | Core crawl/markdown/batch/cache REST endpoints | Done |
| `job_routes.py` | Job CRUD, session status, Cloud Tasks worker | Done |
| `jobs.py` | `JobType` enum (incl. `AGENT_RUN`), `JobManager`, `JobProcessor` | Done |
| `models.py` | All Pydantic models incl. `AgentRunRequest/Response` | Done |

### Infrastructure
| File | Purpose | Status |
|------|---------|--------|
| `config.py` | All env vars incl. agent + provider + ghost config | Done |
| `storage.py` | User-partitioned storage (local filesystem / GCS) | Done |
| `crawler.py` | Playwright crawling engine | Done |
| `markdown.py` | HTML to markdown conversion | Done |
| `browser.py` | Browser automation utilities | Done |
| `browser_pool.py` | Persistent Chromium pool for streaming | Planned |
| `stream.py` | CDP screencast -> WebSocket/MJPEG relay | Planned |

## Agent State Machine

```
INIT -> PLAN -> EXECUTE_TOOL -> OBSERVE -> PLAN -> ... -> RESPOND -> STOP
                     |                                        |
                     +-- policy_denied ---------------------->+
                     +-- max_steps / max_wall_time / max_failures -> STOP
                     +-- no_op_loop (3x empty) ------------> STOP
                     +-- blocked (ghost trigger) -----------> GHOST -> OBSERVE
```

Stop conditions enforced every iteration:
- `max_steps` (default: 12)
- `max_wall_time` (default: 90s)
- `max_failures` (default: 3)
- `no_op_loop` (3 consecutive empty responses)
- `policy_denied` (blocked tool/domain)
- `completed` (agent responds with text)

## Ghost Protocol

When a crawl result signals an anti-bot block (Cloudflare challenge, CAPTCHA,
empty SPA shell), the agent can switch to cloak mode:

1. Take a full-page screenshot via Playwright
2. Send the image to a vision-capable LLM (Claude Sonnet or GPT-4o)
3. Extract content from the rendered pixels
4. Return extracted text with `render_mode: "ghost"` in the trace

This bypasses DOM-based anti-bot detection entirely.

Requires `AGENT_GHOST_ENABLED=true`. Auto-triggers on detected blocks when `AGENT_GHOST_AUTO_TRIGGER=true`.

## Quick Start

### Local Development

```bash
git clone <repo>
cd grub-crawl
cp .env.example .env
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8080
```

### Enable Agent Mode B

```bash
# Add to .env
AGENT_ENABLED=true
OPENAI_API_KEY=sk-...
# or
ANTHROPIC_API_KEY=sk-ant-...
AGENT_PROVIDER=anthropic
```

### Submit an Agent Task

```bash
curl -X POST http://localhost:8080/api/agent/run \
  -H "Content-Type: application/json" \
  -d '{
    "task": "Find the pricing page on example.com and extract plan details",
    "max_steps": 10,
    "allowed_domains": ["example.com"]
  }'
```

## Configuration

### Server
- `HOST` (default: 0.0.0.0)
- `PORT` (default: 8080)
- `DEBUG` (default: false)

### Storage
- `STORAGE_PATH` (default: ./storage)
- `RUNNING_IN_CLOUD` (default: false)
- `GCS_BUCKET_NAME`
- `GOOGLE_CLOUD_PROJECT`

### Authentication
- `DISABLE_AUTH` (default: false)
- `GNOSIS_AUTH_URL` (default: http://gnosis-auth:5000)

### Crawling
- `MAX_CONCURRENT_CRAWLS` (default: 5)
- `CRAWL_TIMEOUT` (default: 30)
- `ENABLE_JAVASCRIPT` (default: true)
- `ENABLE_SCREENSHOTS` (default: false)

### Agent (Mode B)
- `AGENT_ENABLED` (default: false)
- `AGENT_MAX_STEPS` (default: 12)
- `AGENT_MAX_WALL_TIME_MS` (default: 90000)
- `AGENT_MAX_FAILURES` (default: 3)
- `AGENT_ALLOWED_TOOLS` — comma-separated allowlist
- `AGENT_ALLOWED_DOMAINS` — comma-separated allowlist
- `AGENT_BLOCK_PRIVATE_RANGES` (default: true)
- `AGENT_REDACT_SECRETS` (default: true)

### LLM Providers
- `AGENT_PROVIDER` — openai | anthropic | ollama (default: openai)
- `OPENAI_API_KEY`
- `OPENAI_MODEL` (default: gpt-4.1-mini)
- `ANTHROPIC_API_KEY`
- `ANTHROPIC_MODEL` (default: claude-3-5-sonnet-latest)
- `OLLAMA_BASE_URL` (default: http://localhost:11434)
- `OLLAMA_MODEL` (default: llama3.1:8b-instruct)

### Ghost Protocol
- `AGENT_GHOST_ENABLED` (default: false)
- `AGENT_GHOST_AUTO_TRIGGER` (default: true)
- `AGENT_GHOST_VISION_PROVIDER` — inherits from AGENT_PROVIDER
- `AGENT_GHOST_MAX_IMAGE_WIDTH` (default: 1280)

### Live Stream (Planned)
- `BROWSER_POOL_SIZE` (default: 1)
- `BROWSER_STREAM_ENABLED` (default: false)
- `BROWSER_STREAM_QUALITY` (default: 25)
- `BROWSER_STREAM_MAX_WIDTH` (default: 854)

## Response Contract

`POST /api/markdown` returns:

`success`, `url`, `final_url`, `status_code`, `markdown`, `markdown_plain`, `content`, `render_mode`, `wait_strategy`, `timings_ms`, `blocked`, `block_reason`, `captcha_detected`, `http_error_family`, `body_char_count`, `body_word_count`, `content_quality`, `extractor_version`, `normalized_url`, `content_hash`

### Content Quality

- `blocked` — anti-bot/captcha/challenge
- `empty` — very low signal
- `minimal` — thin/error pages
- `sufficient` — usable for summarization

Do not summarize unless `content_quality == "sufficient"`.

### Error Format

```json
{"error": "http_error|validation_error|internal_error", "status": 400, "details": {}}
```

## Development Status

### Phase 1: Core Infrastructure ✅
### Phase 2: Crawling ✅
### Phase 3: Agent Module ✅
- [x] Agent core — state machine, types, errors (W1)
- [x] Unified tool contract — dispatcher with timeout/retry (W2)
- [x] Policy gates — domain allowlist, private-range deny, redaction (W3)
- [x] Observability — EventBus, TraceCollector, RunSummary persistence (W4)
- [x] API wiring — `/api/agent/run`, `/api/agent/status`, JobType.AGENT_RUN (W5)
- [x] Provider adapters — OpenAI, Anthropic, Ollama with fallback (W6)
- [x] Config flags — agent, provider, ghost, stream settings (W7)

### Phase 4: Ghost Protocol ✅
- [x] Cloak-mode trigger detection (W8)
- [x] Screenshot capture pipeline (W8)
- [x] Vision extraction via Claude/GPT-4o (W8)
- [x] Fallback chain in engine (W8)
- [x] Ghost tool for external callers (W8)
- [x] Ghost MCP tool + REST endpoint (W8)

### Phase 5: Live Browser Stream (planned)
- [ ] Persistent browser pool (W9)
- [ ] CDP screencast relay (W9)
- [ ] WebSocket endpoint (W9)
- [ ] MJPEG fallback (W9)

### Phase 6: Hardening
- [ ] Comprehensive test suite
- [ ] Error handling improvements
- [ ] Monitoring and alerting
- [ ] Performance optimization

See [MASTER_PLAN.md](MASTER_PLAN.md) for the full architecture plan.

## License

Grub Crawler Project License
