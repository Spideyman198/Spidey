# Documentation

Design specifications, decision records, and security reviews for Spidey. The documents are the
frozen v1.0 design; implementation tracks them milestone by milestone (see the
[roadmap](04-milestones.md) and [changelog](../CHANGELOG.md)).

## Start here

| Document | What it covers |
| --- | --- |
| [Requirements & threat model](01-requirements.md) | Product and non-functional requirements; the system threat model. |
| [Architecture](02-architecture.md) | System context, containers, bounded contexts, agent orchestration, and the data model. |
| [Repository structure](03-repository-structure.md) | Directory layout and where each concern lives. |
| [Milestones](04-milestones.md) | The M0–M15 delivery plan with exit criteria. |

## Subsystem design

| Document | What it covers |
| --- | --- |
| [Tool plane & MCP](05-tooling-and-mcp.md) | The `ToolRegistry` choke point and the MCP serve/consume strategy. |
| [Retrieval](06-retrieval.md) | Hybrid dense + BM25 + knowledge-graph retrieval and prompt framing. |
| [Memory](07-memory.md) | Conversation history, context assembly, and typed long-term memory. |
| [Events & replay](08-events-and-replay.md) | Event contracts, the transactional outbox, streaming, and deterministic replay. |
| [Observability](09-observability.md) | Tracing, metrics, and logging with OpenTelemetry, Prometheus, and Grafana. |
| [Evaluation](10-evaluation.md) | The evaluation harness, suites, metrics, and tiered CI gates. |

## Security & operations

| Document | What it covers |
| --- | --- |
| [Security](11-security.md) | Trust zones, boundary controls, AI-specific threats, and the security pipeline. |
| [Deployment](12-deployment.md) | Compose and Kubernetes deployment, configuration, and operations. |
| [Repository standards](13-repo-standards.md) | Coding standards, commit conventions, and community files. |
| [Design review](14-design-review.md) | The frozen v1.0 architecture review. |

## Decision records

Architecture Decision Records capture the *why* behind each significant choice —
see [docs/adr/](adr/README.md) (LangGraph orchestration, the Postgres knowledge graph, the LLM
gateway, the Docker sandbox, the MCP strategy, and more).

## Security reviews

Each milestone ships an attack-shaped security review in [docs/security/](security/) — controls
implemented, design decisions with security weight, accepted findings, and adversarial tests
(`m0`–`m9`).

## API reference

The OpenAPI specification is generated from the FastAPI app and kept fresh in CI:
[docs/api/openapi.json](api/openapi.json). It is also served live at `/api/v1/docs` when the stack
is running.
