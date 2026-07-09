# ADR-0012: Multi-provider model registry with config-only routing

**Status:** Accepted · 2026-07-09 · Extends [ADR-0009](0009-llm-gateway.md)

## Context

ADR-0009 established the first-party gateway with an Anthropic-first adapter. The design review
requires provider portability across OpenAI, Anthropic, Gemini, Ollama, vLLM, and Azure OpenAI,
switchable by configuration only — and reaffirms **provider abstraction over framework
abstraction** (no LangChain model wrappers as the seam).

## Decision

A **provider registry** behind the existing `ChatModel`/`Embedder` ports:

- **Adapters (3 cover 6 targets):** `anthropic` (native SDK) · `openai-compatible` (one adapter,
  parameterized by base URL/auth flavor — covers OpenAI, **Ollama**, **vLLM**, and Azure OpenAI's
  endpoint/auth variant) · `gemini` (native SDK). Each adapter declares a capability manifest:
  tool-calling dialect, streaming, max context, embeddings, vision, prices.
- **Routing table in config:** role → (provider, model, params), e.g. planner/coder on a frontier
  model, summarization/distillation on a cheap fast model, embeddings per index. Fallback chains
  per role (primary → secondary on outage/429) are config, evaluated by the gateway's retry layer.
- **Config-only switching, verified:** an integration test boots the stack with each adapter (live
  keys optional; recorded fixtures otherwise) and a conformance suite per adapter (tool-call
  round-trip, streaming, usage accounting) runs in CI — "switching requires configuration only" is
  a tested property, not a slogan.
- Gateway middleware (retries, budgets, metering, caching, redacted capture) is adapter-agnostic —
  written once, applies to every provider.

## Alternatives considered

- **LangChain chat-model classes as the abstraction** — broad coverage but hides retry/usage/raw
  streaming knobs we must own; framework churn becomes our churn (reaffirming ADR-0009). Rejected.
- **LiteLLM (library or proxy)** — genuinely good routing coverage; still deferred: another
  translation layer over the three dialects we already need to understand deeply for tool-calling
  fidelity. Could later slot in *behind* `ChatModel` without touching callers.
- **One adapter per provider (6 adapters)** — needless duplication when four targets speak the
  OpenAI dialect. Rejected for the parameterized adapter.

## Consequences

- (+) Local/self-hosted story (Ollama, vLLM) comes free with the OpenAI-compatible adapter —
  air-gapped demos and cost-free CI canaries.
- (+) Model choice becomes an eval-driven config decision per role (doc 10 gates routing changes).
- (−) Tool-calling dialect differences (esp. Gemini) are ours to normalize — bounded by the
  conformance suite; capability manifests keep unsupported features explicit instead of silently
  degraded.
