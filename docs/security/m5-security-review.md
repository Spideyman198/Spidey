# M5 Security Review

**Date:** 2026-07-16 · **Scope:** knowledge graph & graph-augmented retrieval — reference
extraction, `graph_nodes`/`graph_edges` with recursive-CTE traversals, graph API, fact expansion
· **Verdict: PASS**

## 1. Controls implemented and verified this milestone

| Control (requirement) | Implementation | Verification |
| --- | --- | --- |
| Bounded traversal (DoS / ADR-0003) | Every recursive CTE has three rails: a `depth` cap, a visited-node accumulator so cycles (mutual recursion, inheritance diamonds) terminate, and a final `LIMIT`; the API clamps `depth`/rows to `graph_query_max_*` regardless of caller input | `test_graph_flows.py` traversals return finite results on a cyclic call graph; API depth clamped in `_clamp_depth` |
| SQL-injection safety | Each of the four traversals is a **fully static SQL constant** — no f-string, `.format`, or concatenation anywhere — with every caller value (`workspace_id`, `path`, `qualified_name`, `depth`, `limit`) passed as a bound parameter; edge-kind filters are literal in the query text, so no value is ever assembled into SQL | bandit B608 clean (no suppressions); parameters via SQLAlchemy `text()` bindings |
| Per-workspace tenant isolation | Every node/edge row carries `workspace_id`; the seed CTE and all edge joins filter on it, so a traversal cannot cross a tenant boundary; graph API endpoints verify workspace ownership first | `test_graph_flows` isolation; ownership check on all four endpoints (404 for non-owner via the shared workspace guard) |
| No graph/symbol drift | The graph is rebuilt from the workspace's current symbols + references inside the *same* index transaction (delete-then-insert), so a crash leaves the prior committed graph, never a half-built one | graph rebuild in `IndexService.reindex`; committed with symbols in one session |
| FK integrity on rebuild | Nodes are flushed before edges reference them; edges FK both endpoints with `ON DELETE CASCADE`, so a workspace deletion removes its whole graph | `rebuild` node-before-edge flush; FK cascade in migration `b2c3d4e5f6a7` |
| Retrieval-injection posture unchanged (SEC-PI) | Graph expansion emits *facts built from code identifiers* (qualified names + path:line), not raw file text; retrieved chunks continue through the M4 inert data-frame before any prompt use | facts rendered by `GraphNeighbor.as_fact`; framing path unchanged |

## 2. Design decisions with security weight

- **Cycle termination is explicit, not incidental.** A code call graph is densely cyclic. Rather than
  rely on the depth cap alone (which bounds but can still fan out exponentially within the cap), each
  walk carries a visited-node array and refuses to re-enter a node. Depth cap + visited set + row
  limit together make every traversal linear and finite.
- **Graph in Postgres, bounded by the port.** Per ADR-0003 the graph is Postgres tables + CTEs, not a
  graph DB. The `GraphStore` port's mandatory `depth`/`limit` parameters make the "no unbounded graph
  queries" constraint a compile-time fact, not a convention — there is no method that walks freely.
- **Static queries over DRY.** The four traversals are written out in full rather than assembled from
  a shared template. The duplication is deliberate: it makes injection-impossibility self-evident to a
  reviewer and to every SAST scanner (nothing is built from a value), which a parameterized
  string-builder — however carefully guarded — cannot demonstrate as cleanly.
- **Name-based resolution is an over-approximation in the safe direction.** Ambiguous names link to
  all candidates (capped), so an impact set may include a false positive but never *misses* a real
  dependent — the correct bias for "what could this change break." Documented as name-based, not
  type-aware (a revisit-if-evals-demand-it item).
- **Expansion is eval-gated and feature-flagged.** `graph_expansion_enabled` defaults on only because
  the retrieval eval (run with the graph built) shows precision/recall/MRR hold at or above the M4
  baselines — the M5 exit criterion. If a future change regressed retrieval, the flag turns it off
  without a code change.

## 3. Accepted findings / deliberate scoping

- **Full graph rebuild per index pass.** The graph is recomputed from the current symbols/references
  each time anything changes, rather than diffing edges incrementally. Correct and drift-free, and
  bounded by workspace size; true incremental edge maintenance is a future optimization noted in the
  code.
- **Import-edge precision is best-effort.** Import references resolve by name to workspace nodes;
  external library imports resolve to nothing and are dropped. Cross-repo name collisions could in
  principle create a spurious intra-repo import edge — low impact, and imports are the least
  load-bearing of the four edge kinds.
- **Facts are directional but not type-checked.** Fact direction comes from edge orientation, which is
  accurate; the underlying call/inherit resolution is still name-based, so a fact inherits that
  imprecision. Facts always carry `path:line` provenance so a reader can verify.
- **Actions still tag-pinned** (carried from M0 §3; scheduled M15).

## 4. Attack-shaped / robustness tests added

Cyclic-graph traversal termination (recursive call + inheritance), per-workspace isolation and API
ownership (404 for non-owner), unknown-symbol 404, depth/row clamping, and graph-build determinism
(nodes before edges, dedup, self-loop suppression). Retrieval eval re-run with the graph built proves
expansion does not regress ranked-hit quality.

## 5. Carry-forward

M6 adds the LLM gateway + tool plane; the graph query methods become read-only MCP tools behind the
tool registry's trust tiers. Graph facts feed context assembly in M7 through the same inert data-frame
as retrieved chunks. Type-aware call resolution and incremental edge maintenance remain eval-gated
future work.
