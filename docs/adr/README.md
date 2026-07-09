# Architecture Decision Records

Immutable once **Accepted** — a changed decision gets a new ADR that supersedes the old one.
Format: Context → Decision → Alternatives considered → Consequences.

| ADR | Title | Status |
|---|---|---|
| [0001](0001-modular-monolith.md) | Modular monolith with hexagonal bounded contexts | Accepted |
| [0002](0002-langgraph-orchestration.md) | LangGraph for agent orchestration | Accepted |
| [0003](0003-postgres-knowledge-graph.md) | Knowledge graph in PostgreSQL, not a graph DB | Accepted |
| [0004](0004-qdrant.md) | Qdrant as the vector store (amended: sparse BM25 hybrid) | Accepted |
| [0005](0005-celery.md) | Celery + Redis for background execution | Accepted |
| [0006](0006-sse-streaming.md) | SSE over Redis Streams for client streaming | Accepted |
| [0007](0007-docker-sandbox.md) | Ephemeral Docker containers as the execution sandbox | Accepted |
| [0008](0008-mcp-strategy.md) | MCP posture: serve first-class, consume gated | **Superseded by 0010** |
| [0009](0009-llm-gateway.md) | Own thin LLM gateway; LangChain only at the interface level | Accepted (extended by 0012) |
| [0010](0010-mcp-tool-plane.md) | MCP as the first-class tool plane | Accepted |
| [0011](0011-events-observation-not-control.md) | Domain events for observation, not agent control flow | Accepted |
| [0012](0012-model-provider-registry.md) | Multi-provider model registry, config-only routing | Accepted |
| [0013](0013-event-sourced-replay.md) | Event-sourced replay with content-addressed artifacts | Accepted |
| [0014](0014-kubernetes-readiness.md) | Kubernetes readiness: compose-first delivery, K8s-shaped design | Accepted |
