# ADR-0002: LangGraph for agent orchestration

**Status:** Accepted · 2026-07-09

## Context
The agent runtime needs: multi-role graph execution with cycles (review/debug loops), durable
pause/resume across process restarts, human-in-the-loop interrupts for approval gates (FR-6.2), and
replayable state history — with runs that may live for hours.

## Decision
LangGraph as the orchestration engine, with a PostgreSQL checkpointer. Nodes are our own typed
functions calling our own tool registry and LLM gateway; LangGraph provides the state machine,
checkpointing, and interrupt mechanics only.

## Alternatives considered
- **Hand-rolled state machine** — full control and no dependency risk, but durable checkpointing +
  interrupt/resume + time-travel is weeks of subtle infrastructure that isn't this project's
  differentiator. Rejected for scope economics; our node/tool code stays framework-thin so an
  extraction later is contained.
- **Temporal** — excellent durability semantics, but adds a heavyweight service + programming model
  for what LangGraph covers at library weight. Rejected for v1.
- **CrewAI / AutoGen** — higher-level agent abstractions that would own our prompts and control
  flow; too opinionated where we need precise security control (per-role tool scoping, budgets).
  Rejected.

## Consequences
- (+) Checkpoint/interrupt/replay for free; Postgres checkpointer matches our persistence story.
- (+) Graph topology is explicit and diagrammable — good for audit and for the portfolio narrative.
- (−) Framework coupling risk → mitigated: nodes depend on our ports, not LangChain types, except at
  the graph seam; checkpointer tables are ours to migrate.
- (−) LangGraph API churn → pinned versions, upgrade via dedicated PRs with the eval harness as the
  regression gate.
