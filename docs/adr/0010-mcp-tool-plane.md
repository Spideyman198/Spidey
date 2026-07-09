# ADR-0010: MCP as the first-class tool plane

**Status:** Accepted · 2026-07-09 · Supersedes [ADR-0008](0008-mcp-strategy.md)

## Context
ADR-0008 treated MCP as an optional integration bolted onto a proprietary tool registry. The design
review elevated the requirement: MCP should be the architectural contract of the tool plane, with
pluggable servers (filesystem, git, GitHub, Docker, terminal, browser, PostgreSQL, custom) — while
security invariants (path allow-lists, command policy, approval gates) must remain impossible to
bypass through any transport.

## Decision
The tool plane is **MCP-shaped end to end**: ToolSpecs use MCP-compatible schemas/annotations; the
`ToolRegistry` is the single invocation choke point; providers are either **native in-process**
(filesystem, git, terminal/sandbox, GitHub-write — the security-critical set) or **mounted MCP
clients** (GitHub-read, PostgreSQL, browser, future custom servers). Everything is servable over
Spidey's own MCP server under the same authN/Z, side-effect classes, and approval gates as REST.
External servers get: config-only registration with namespacing, tool-definition **pinning with
drift alarms**, description sanitization, trust tiers, scrubbed-env child processes, per-server
budgets and circuit breakers. Full design: [docs/05-tooling-and-mcp.md](../05-tooling-and-mcp.md).

## Alternatives considered
- **All tools as external MCP servers (maximal MCP)** — architecturally pure, but moves
  `SafeFileSystem` and `CommandPolicy` out of process, turning our security invariants into network
  trust assumptions, and adds serialization latency to the hottest path. Rejected: security-critical
  tools stay native; MCP is their *transport*, not their implementation.
- **Proprietary registry, MCP as adapter (ADR-0008 position)** — underweights interop; two contract
  shapes to maintain. Superseded.

## Consequences
- (+) One contract serves native tool-calling, MCP serving, and MCP consumption; new capability =
  config, not platform code.
- (+) Security review has exactly one choke point to audit.
- (−) MCP spec evolution risk → pinned SDK, conformance tests, drift alarms double as spec-change
  detectors.
- (−) Approval-over-MCP UX (pending status while a human approves in Spidey) is nonstandard —
  documented for client authors.
