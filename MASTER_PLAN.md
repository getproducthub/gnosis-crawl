# Master Plan - gnosis-crawl Agent Module

## Scope
Build a dual-mode agent architecture where:
1. External agents remain first-class (`Mode A`, default).
2. Internal micro-agent loop is optional and policy-bound (`Mode B`, opt-in).

The same tool contracts and trace schema must work in both modes.

## Goals
1. Keep current external crawl APIs/tool calls backward compatible.
2. Add an internal bounded loop with strict policy gates and typed errors.
3. Emit replayable traces for all tool executions.
4. Keep internal agent disabled by default.

## Workstreams

### W1. Agent Core
Files:
- `app/agent/types.py`
- `app/agent/errors.py`
- `app/agent/dispatcher.py`
- `app/agent/engine.py`

Deliverables:
1. State machine primitives:
- `RunState`: `INIT`, `PLAN`, `EXECUTE_TOOL`, `OBSERVE`, `RESPOND`, `STOP`, `ERROR`
- `StopReason`: `max_steps`, `max_wall_time`, `max_failures`, `no_op_loop`, `policy_denied`, `completed`
2. Normalized actions/results:
- `AssistantAction` => `Respond(text)` or `ToolCalls([ToolCall])`
- `ToolCall` => `id`, `name`, `args`
- `ToolResult` => `ok|err`, `payload`, `error_code`, `retriable`
3. Loop runner:
- `run_task(task, config, context) -> RunResult`
- `plan(run_ctx) -> AssistantAction`
- `step(run_ctx, action) -> StepResult`
4. Stop conditions enforced every iteration.

### W2. Unified Tool Contract
Files:
- `app/tools/tool_registry.py`
- `app/agent/dispatcher.py`

Deliverables:
1. Normalized descriptor:
- `name`, `args_schema`, `timeout_ms`, `retry_profile`, `side_effect_class (read|write|auth)`
2. Shared usage by:
- External AHP tool execution path.
- Internal agent dispatcher.
3. Dispatcher behavior:
- Arg validation
- Timeout + retry handling
- Typed error normalization (no raw exceptions to loop callers)

### W3. Policy and Safety
Files:
- `app/policy/domain.py`
- `app/policy/gate.py`
- `app/policy/redaction.py`

Deliverables:
1. Domain allowlist + private network deny by default.
2. Pre-tool and pre-fetch policy checks.
3. Prompt-injection quarantine transform for crawled text before planning.
4. Secret redaction before logs and persisted outputs.

### W4. Observability and Trace
Files:
- `app/observability/trace.py`
- `app/observability/events.py`

Deliverables:
1. Shared step trace schema:
- `run_id`, `step_id`, `tool_name`, `args_hash`, `duration_ms`, `status`, `error_code`, `artifacts[]`, `policy_flags[]`
2. Persist trace/artifacts to session/job storage.
3. Replay-friendly run summary output.

### W5. API + Job Wiring
Files:
- `app/job_routes.py`
- `app/jobs.py`
- `app/models.py` (if request/response expansion needed)

Deliverables:
1. Convert `/api/wraith` from placeholder to real submission.
2. Add `JobType.AGENT_RUN`.
3. Add processor branch for internal agent execution.
4. Preserve external mode parity when internal agent is disabled.

### W6. Provider Abstraction
Files:
- `app/agent/providers/base.py`
- `app/agent/providers/openai_adapter.py`
- `app/agent/providers/anthropic_adapter.py`
- `app/agent/providers/ollama_adapter.py`

Deliverables:
1. Provider interface:
- `LLMAdapter.complete(actions, context) -> AssistantAction`
2. Normalized response mapping:
- OpenAI tool-calls
- Anthropic `tool_use`/`tool_result`
- Ollama `tool_calls`/tool messages
3. Fallback + retry:
- Retry transient once, then rotate provider.

Defaults:
1. OpenAI: `gpt-4.1-mini`
2. Anthropic: `claude-3-5-sonnet-latest`
3. Ollama: `llama3.1:8b-instruct`

### W7. Config and Startup Validation
Files:
- `app/config.py`
- startup validation path in `app/main.py` (or dedicated validator module)

Deliverables:
1. Add:
- `agent.internal.enabled` (default `false`)
- `agent.internal.max_steps` (default `12`)
- `agent.internal.max_wall_time_ms` (default `90000`)
- `agent.internal.max_failures` (default `3`)
- `agent.internal.allowed_tools` (explicit allowlist)
- policy flags (`allowed_domains`, private-range blocking, redaction, raw HTML persistence)
2. Fail closed on invalid config.

## Error Semantics
Use machine-readable typed errors:
1. `validation_error`
2. `policy_denied`
3. `tool_timeout`
4. `tool_unavailable`
5. `execution_error`

Each response includes retry hint metadata when applicable.

## Test Plan

### Unit
1. Stop condition triggers.
2. Policy gate decisions.
3. Dispatcher normalization/retry behavior.

### Integration
1. External mode parity with internal disabled.
2. Internal bounded multi-step completion.
3. Fail-closed behavior on policy violations.

### Provider Contract
1. OpenAI mapping fidelity.
2. Anthropic mapping fidelity.
3. Ollama mapping fidelity.

### Security
1. Prompt-injection quarantine blocks forbidden actions.
2. Secret redaction applied in logs and final outputs.

## Rollout
1. Phase 1: internal loop + policy + trace (`disabled` by default).
2. Phase 2: provider adapters enabled via env.
3. Phase 3: hardening/perf tuning + soak tests.

## Acceptance Criteria
1. External clients remain backward compatible.
2. Internal mode solves bounded multi-step tasks.
3. Policy-denied actions are blocked and logged with reason.
4. Shared trace schema for both internal and external modes.
5. Internal mode requires explicit opt-in.
