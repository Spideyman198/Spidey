# ADR-0008: MCP posture — serve first-class, consume gated

**Status:** Superseded by [ADR-0010](0010-mcp-tool-plane.md) · 2026-07-09

> The 2026-07-09 design review elevated MCP from an optional integration to the first-class
> contract of the tool plane. The security posture below (serve gated, consume untrusted) is
> preserved and extended in ADR-0010; the "optional transport" framing is retired.

## Context
FR-6.4 requires Model Context Protocol integration. MCP cuts both ways: exposing our tools to
external clients (Claude Code, IDEs), and consuming third-party MCP servers as extra agent tools.
The latter imports untrusted tool definitions and outputs into our prompt context.

## Decision
1. **Serve:** the `ToolRegistry` is exported as an MCP server. Tools carry the same auth, RBAC,
   side-effect classes, and approval gates regardless of caller — MCP is a transport, not a bypass.
   Read-only tools (search, graph queries, file read) ship first; mutating tools follow once the
   approval flow is proven over MCP.
2. **Consume:** external MCP servers are disabled by default, enabled per-server via config
   allow-list, mapped into the registry as `untrusted`-origin tools: their descriptions are
   sanitized, their outputs enter prompts only inside inert data frames, and they can never be
   classed better than `write` (i.e., always below auto-trusted reads).

## Alternatives considered
- **Proprietary tool API only** — simpler, but forfeits the interop story that MCP exists for and
  that this portfolio should demonstrate. Rejected.
- **Unrestricted MCP consumption** — a documented prompt-injection and tool-shadowing vector
  (malicious server descriptions steering the model). Rejected.

## Consequences
- (+) One tool abstraction serves LLM native tool-calling, MCP serving, and MCP consumption.
- (+) Security invariants live in the registry, so no transport can route around approvals.
- (−) MCP spec evolution → version-pinned SDK, conformance tests in CI.
