# M6 Security Review

**Date:** 2026-07-16 · **Scope:** LLM gateway (registry + 3 adapters + middleware), tool plane +
MCP (registry choke point, native tools, Spidey MCP server, external MCP consuming), event backbone
(outbox → Redis Streams → consumers) + SSE · **Verdict: PASS**

## 1. Controls implemented and verified this milestone

| Control (requirement) | Implementation | Verification |
| --- | --- | --- |
| Keys never in logs/spans/events | Provider keys are `SecretStr` (never logged), passed only into adapter clients; interaction capture scrubs every request/response body at capture time before it touches disk (`scrub_text`) | `PostgresInteractionCapture` redaction; keys held as `SecretStr` in config |
| Budgets/metering un-bypassable (NFR-5) | Enforced in the one `Gateway` seam every call passes through; agents never hold an adapter, so there is no path around budget checks or `LlmCallCompleted` metering | `test_gateway` budget block/record + metering; ADR-0009 single-seam |
| Tool plane single choke point | Every invocation (native or MCP, agent or MCP caller) flows through `ToolRegistry.invoke`: RBAC, JSON-Schema validation, side-effect gating, per-call timeout, non-trusted output sanitization, start/complete events | `test_tool_registry` (8 cases); `SpideyMcpTools` routes through the same registry |
| Read-only rollout enforced | Write/destructive tools are denied (`allow_mutations=False`) until the M7 approval flow; the denial is an audited event, not a silent drop | `test_write_tool_gated_until_approval`; `SpideyMcpTools` maps `destructiveHint` |
| MCP rug-pull defense (pinning + drift) | A mounted server's tool set is hashed and compared to the reviewed pin; a mismatch **disables** the server (no tools exposed) and fires a `spidey_mcp_drift_alarms` counter until re-approval | `test_mcp_provider` drift disables + hides tools |
| MCP tool-poisoning defense | Untrusted-server descriptions are injection-screened and **withheld** on a hit before entering any prompt; tool *output* is scrubbed + injection-flagged by the registry | `test_untrusted_injection_description_is_withheld`; registry `_sanitize` |
| MCP is a transport, not a principal | The Spidey MCP server resolves the caller via the same bearer→identity→RBAC path as REST and routes through the registry — identical authZ | `SpideyMcpTools.list_tools` is RBAC-filtered by caller role |
| Event integrity + stream authZ | Transactional outbox (event committed with its state change); append-only `run_events`; SSE `/runs/{id}/events` authorizes on a Redis-recorded run owner (non-owner → 404) | `test_event_plane` outbox→persist + relay idempotency; SSE ownership 404 |

## 2. Design decisions with security weight

- **One seam, enforced by construction.** Budgets, metering, retries, and redacted capture live only in
  the gateway; the tool plane's invariants live only in the registry. Callers receive *services*, never
  raw adapters or providers, so "you cannot bypass the budget/RBAC" is a structural fact, not a rule.
- **Trust tiers drive sanitization, not convenience.** Native tools are `trusted` (our code) and their
  output is pre-framed; `verified`/`untrusted` MCP output is treated as hostile — scrubbed, injection-
  screened, size-capped — before it can steer a model. Untrusted descriptions get the same treatment at
  mount time.
- **Drift is fail-closed.** A changed tool set disables the server rather than trusting the new
  definitions; re-enabling is an explicit re-pin. This closes the documented "establish trust, then swap
  the description" MCP attack.
- **A tool never raises across the registry.** Failures (timeout, dead MCP server, denial) are typed
  `ToolResult` values, so a hostile or broken provider degrades a run instead of crashing it — and every
  outcome is an event.

## 3. Accepted findings / deliberate scoping

- **Approval flow is M7.** Write/destructive tools are gated (denied) rather than routed to a human
  approver, because the approval interrupt + inbox land with the agent runtime. M6 ships read-only tools,
  matching the doc-05 rollout.
- **MCP transport adapters are thin SDK glue.** `SdkMcpSession` and the streamable-HTTP mount are not
  unit-tested offline (they need a live server); the security logic they wrap (`McpProvider` pinning /
  drift / sanitize, `SpideyMcpTools` mapping) is fully tested behind ports. stdio scrubbed-env launching
  and per-server circuit breakers are wired in M7 alongside the run runtime.
- **Live multi-provider + conformance are key-gated.** The conformance suite (complete/stream/tool
  round-trip per adapter) skips without keys, exactly like the T2 evals — it is a tested property in CI
  when credentials are configured, never a hard failure without them.
- **Long-held transaction in the scripted chat.** The M6 demo runs the whole turn in one DB transaction
  (LLM calls included) for simplicity; the M7 run lifecycle replaces this with per-step transactions.
- **Actions still tag-pinned** (carried from M0 §3; scheduled M15).

## 4. Attack-shaped / robustness tests added

Tool-plane RBAC denial, arg-schema rejection, write-gating, timeout→unavailable, and non-trusted output
sanitization; MCP drift-disable, injection-description withholding, and server-error-as-value; gateway
budget block; SSE run-ownership 404; and the scripted-chat plane end-to-end (user→LLM→tool→LLM→events).

## 5. Carry-forward

M7 (agent runtime) turns the scripted chat into the LangGraph planner/coder/reviewer graph, adds the
approval interrupt that ungates write/destructive tools, per-step transactions, stdio MCP child-process
launching (scrubbed env) + circuit breakers, and full replay (`run_events` + `llm_interactions` are
already captured here). Provider fallback + budgets carry through unchanged.
