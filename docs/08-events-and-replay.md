# 08 — Domain Events & Replay System

## 1. The control-flow decision (read first)

Domain events are used for **observation, persistence, and integration — not for agent control
flow**. The Planner does not "emit TaskCreated and hope someone reacts": LangGraph edges remain the
single, checkpointed, interruptible control path. Events are **facts published after the fact**.

Why ([ADR-0011](adr/0011-events-observation-not-control.md)): event-choreographed agent steps would
re-implement — badly — exactly what LangGraph gives us (durable state, interrupts, replayable
transitions), while making the execution order implicit and un-debuggable. What events *are* the
right tool for: the run timeline, audit, replay, dashboard, memory distillation, and eval capture —
all consumers that must not be able to affect the run.

## 2. Event contract

```
EventEnvelope {
  event_id: ULID,                # ordering + idempotency key
  event_type: str,               # e.g. "agents.task_created"
  schema_version: int,           # per-type, additive evolution; breaking change = new type
  occurred_at: datetime,
  run_id, session_id, workspace_id, actor,   # correlation
  trace_id, span_id,             # OTel linkage — every event joins a trace
  payload: <typed per event_type, Pydantic-validated>
}
```

Contracts live in `platform/events.py` as versioned Pydantic models — the single source of truth
for producers, consumers, the TypeScript event reducer (generated), and replay.

## 3. Event taxonomy (core set)

| Producer | Events |
| --- | --- |
| `agents` | RunStarted, PlanCreated, **TaskCreated**, TaskStateChanged, NodeEntered/Exited, ApprovalRequested/Resolved, RunCompleted/Failed/Escalated |
| `agents` (roles) | **CodeGenerated** (diff ref), **ReviewCompleted** (verdict), **TestsPassed/TestsFailed** (results ref), **FixGenerated** (diff ref), DocsUpdated |
| `llm` | LlmCallCompleted (model, tokens, latency, cost, interaction ref) |
| tool plane | ToolInvocationStarted/Completed (tool, side-effect class, outcome) |
| `workspaces` | RepoIngested, WorkspaceSynced, BranchCreated, CommitCreated, PrOpened |
| `codeintel` | IndexSnapshotCompleted, SuspectContentFlagged |
| `memory` | MemoryDistilled, MemoryRecalled, MemoryDeleted |
| `execution` | SandboxCreated/Destroyed, CommandExecuted, PolicyViolationBlocked |
| `identity` | login/refresh/authz-denied events (audit-focused) |

## 4. Message boundaries & delivery

```mermaid
flowchart LR
    subgraph produce[Producers - in-transaction outbox]
        agents & tools & llm & ws[workspaces]
    end
    outbox[(PG outbox table)] --> relay[Outbox relay]
    produce --> outbox
    relay --> streams[(Redis Streams\nrun:{id}:events + firehose)]
    streams --> sse[SSE relay → UI]
    streams --> cg1[Consumer group: persister\n→ run_events PG]
    streams --> cg2[Consumer group: audit projector]
    streams --> cg3[Consumer group: metrics projector]
    streams --> cg4[Consumer group: memory distiller trigger]
```

- **Within a context:** plain method calls. **Cross-context commands** (do something):
  application-service calls, synchronous, explicit. **Cross-context facts** (something happened):
  events. No event ever *commands*.
- **Transactional outbox:** events are written to Postgres in the same transaction as the state
  change they describe, then relayed to Redis Streams — no lost or phantom events on crash.
- **Delivery:** at-least-once via consumer groups; consumers are idempotent on `event_id`.
  Ordering is guaranteed per run stream only (all consumers key on run_id).
- **Retention:** Redis streams are capped (`MAXLEN ~`) and deleted after the persister confirms;
  Postgres `run_events` is the durable record.

## 5. Replay system ([ADR-0013](adr/0013-event-sourced-replay.md))

Every run is reconstructable and re-executable from what we store:

| Stored | Where | Notes |
| --- | --- | --- |
| Events (all of §3) | `run_events` | the spine: ordered, trace-linked |
| Prompts & responses | `llm_interactions` + artifact store | full request/response per LLM call; secret/PII-redacted at capture; large bodies content-addressed |
| Tool invocations | `tool_invocations` | args, result ref, side-effect class, approval linkage |
| Diffs & artifacts | content-addressed artifact store (SHA-256, local volume; S3-compatible port for later) | dedupe for free; referenced by hash from events |
| Token usage / latency / cost | `token_usage` + event attributes | aggregable per run/session/model |
| Failures | RunFailed payloads + linked traces | exception class, node, budget state |

### Replay modes

1. **Timeline reconstruction** — deterministic re-render of any run in the UI from `run_events`
   (this is also just how the dashboard works for live runs; live and historical views are the same
   reducer over the same events).
2. **Golden re-execution** — re-run the graph with recorded LLM responses and tool results played
   back as fixtures. Deterministic, offline, fast: this is how agent-behavior regressions are
   tested in CI (a prompt refactor must reproduce recorded decision sequences or explicitly
   re-bless them) — the bridge between replay and the evaluation harness (doc 10).
3. **Comparative re-run** — same goal, live execution under a new model/prompt/config; the eval
   harness diffs outcomes, cost, and latency against the recorded baseline.

**Retention & privacy:** full-fidelity replay data (prompt bodies, artifacts) has a configurable
retention window (default 30 days) after which bodies are dropped and only events + episodic
summaries + metrics remain. Redaction happens **at capture time**, not at read time — secrets never
land on disk.
