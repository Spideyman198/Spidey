# ADR-0009: Own thin LLM gateway; LangChain only at the interface level

**Status:** Accepted · 2026-07-09

## Context
Every LLM interaction needs: provider portability, native tool-calling, streaming, retries with
exponential backoff, token metering and budgets (NFR-5), caching, and full observability (tokens,
latency, model as trace attributes). The stack suggestion includes LangChain "only where it provides
real value".

## Decision
A first-party `llm` context defines provider-neutral ports (`ChatModel`, `Embedder`) and domain
types (`ChatRequest`, `ToolCall`, `Usage`). The first adapter wraps the Anthropic SDK directly
(default model: `claude-sonnet-5` for agent work, configurable per role; embeddings via a
configurable embedding provider). Gateway middleware layers add retry/backoff+jitter, budget
enforcement, metering, and caching. LangChain/LangGraph interact with our gateway through a thin
shim only where LangGraph requires model handles — LangChain chains, memories, retrievers, and
agents are **not** used.

## Alternatives considered
- **LangChain as the abstraction layer** — broad provider coverage, but its abstractions are wide,
  fast-moving, and hide exactly the knobs we must control (retry policy, token accounting, raw
  streaming events); debugging through its layers is costly. Rejected as the core seam.
- **LiteLLM proxy** — good multi-provider routing, but an extra service and another place where
  API keys and prompts flow; overkill for one primary provider in v1. Deferred — could slot in
  *behind* our `ChatModel` port later without touching callers.
- **Direct SDK calls sprinkled through agent code** — no seam for metering, budgets, or provider
  swap; untestable without network. Rejected.

## Consequences
- (+) Budgets, metering, and retries are enforced in exactly one place; agents cannot bypass them.
- (+) Unit tests run against a deterministic fake `ChatModel` — the whole agent graph is testable
  offline; provider swap = one adapter.
- (−) We own tool-calling schema translation per provider — bounded cost while providers converge
  on similar tool APIs, and the eval harness catches translation regressions.
