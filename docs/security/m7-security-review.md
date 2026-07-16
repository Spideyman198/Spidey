# M7 Security Review

**Date:** 2026-07-17 · **Scope:** agent runtime — run lifecycle & state machine (`RunService`,
`RunStatus` transitions), LangGraph graph (plan / approve / execute / budget gate / finalize) on a
durable Postgres checkpointer, side-effect approval invariant at the `ToolRegistry`, per-run budgets,
owner-scoped run/approval REST surface, and deterministic golden replay · **Verdict: PASS**

## 1. Controls implemented and verified this milestone

| Control (requirement) | Implementation | Verification |
| --- | --- | --- |
| No side effect without a resolved approval | The `ToolRegistry` choke point runs a write/destructive tool only when presented an `Approval` that is `approved`, is for **that exact tool**, and (when the call is part of a run) for **that same run**; reads are the only un-gated path | `test_tool_registry` approval-gate cases: runs with a matching approval; denied when pending, for another tool, or for another run |
| A grant is never transferable | The approval check binds `approval.tool == spec.name` **and** `approval.run_id == context.run_id` before permitting; a valid grant for one tool/run cannot unlock another | `test_write_tool_denied_when_approval_is_for_another_tool` / `…_another_run` |
| Human gate before execution | The graph drafts a plan then blocks on a durable `interrupt` (`awaiting_approval`); execution only begins when the owner resumes, optionally after editing the plan — no autonomous execution precedes a human | `test_graph` plan→interrupt→resume→execute; `RunService.resume` refuses while approvals are unresolved |
| Runaway prevention (NFR-5) | Per-run budget (steps/tokens/cost) is charged each step; on exhaustion the run halts into `needs_human` at a durable budget gate rather than continuing — a human must grant a fresh window | `test_budget_exhaustion_pauses_then_resumes` |
| Owner-scoped control surface | Every `RunService` method resolves the run through `get_run(owner_id, run_id)`; a non-owner gets `not found`. REST create/get/list/cancel/resume, plan get/edit, approvals list/resolve are all owner-scoped; SSE authorizes on the Redis-recorded owner | `test_run_service` owner-scoping; SSE ownership 404 (carried from M6) |
| State machine integrity | Human-driven transitions are guarded by `can_transition`; illegal moves raise `ConflictError`. Terminal runs reject cancel/resume/edit | `test_run_domain` transition table; `test_run_service` conflict paths |
| Pauses survive a restart | The graph compiles with a Postgres checkpointer keyed by `thread_id = run_id`; an interrupted run resumes from its checkpoint after an API/worker restart via `Command(resume=…)` | Offline proof with `MemorySaver` (`test_graph`); worker uses `AsyncPostgresSaver` |
| A crash never strands a run | The run worker records a mid-run exception as `failed` in a **fresh** session (the run's own session is rolled back) and re-raises for Celery logging — no run sticks in `running` | `agent_run._mark_failed` |
| Deterministic replay (exit criterion) | A T1, LLM-free suite reconstructs a run's timeline (plan, transcript, status, event sequence) from committed fixtures and fails on any non-determinism or drift from the golden | `test_replay_eval` golden run; `test_replay` suite mechanics |

## 2. Design decisions with security weight

- **The approval invariant is structural, not procedural.** "No side effect without a resolved,
  scoped human approval" is enforced at the same single `ToolRegistry.invoke` that already owns RBAC,
  schema validation, and sanitization — the one place every native or MCP call passes through. There is
  no second path to a mutation, so the invariant holds by construction rather than by reviewer vigilance.
- **Grants are least-privilege and single-use in spirit.** An approval unlocks exactly one tool for one
  run; it is checked, not trusted. This blocks confused-deputy reuse (an approval for a benign tool
  cannot authorize a dangerous one) and cross-run replay of a captured grant.
- **Human-in-the-loop is a durable pause, not a busy wait.** Plan approval and budget exhaustion both
  use LangGraph `interrupt` with a Postgres checkpoint, so the run costs nothing while parked and cannot
  be lost to a restart. The only work preceding an `interrupt` is the interrupt itself, so re-running the
  node on resume is idempotent — no duplicated plan, approval, or event.
- **Budgets fail into a human, not into silence.** Exhaustion transitions to `needs_human` and stops;
  continuing requires an explicit human-granted window. Combined with the gateway's own per-scope token/
  cost ceiling (M6), spend is bounded at both the run and the tenant layer.
- **The run is owned end to end.** The domain state machine, the service control surface, and the SSE
  stream each independently scope to the owner; losing any one does not widen access.

## 3. Accepted findings / deliberate scoping

- **No production write tool ships in M7.** M7 delivers the *mechanism* — the approval model, the
  registry gate, and the owner-scoped resolve surface — proven with a fake mutation tool. The first real
  mutating tool (file edit / command execution) lands in M8 and rides this gate unchanged; until then the
  agent's execute path exercises read tools only, and any write request is denied at the choke point.
- **Graph-initiated approval request is M8.** Because no write tool exists yet, the graph does not yet
  *raise* an approval mid-execution and then invoke the approved mutation; that half-node pair arrives
  with the write tools it gates. The security-relevant half — that a mutation cannot run without a valid
  approval — is enforced and tested now.
- **Budget resume grants a fresh step window.** Resuming a budget-halted run resets the consumed step
  count (token/cost totals are preserved), reflecting that a human explicitly accepted continued spend.
  This is a policy choice, not a bypass — the human remains the gate.
- **Per-run checkpointer connection.** The worker opens one `AsyncPostgresSaver` connection per run and
  calls `setup()` idempotently; connection pooling for the checkpointer is a performance item for a later
  milestone, not a correctness or security concern.
- **stdio MCP child-process launching + per-server circuit breakers** remain M8 (carried from M6).
- **Actions still tag-pinned** (carried from M0 §3; scheduled M15).

## 4. Attack-shaped / robustness tests added

Approval gate: mutation **denied** with a pending, wrong-tool, or wrong-run approval and **allowed** only
with an exact match; plan cannot execute before a human resume; illegal state transitions rejected;
budget exhaustion halts into `needs_human` and only a granted window continues; a worker exception marks
the run `failed` (never stranded `running`); and the golden-replay suite fails on any non-deterministic or
drifted timeline.

## 5. Carry-forward

M8 (code editing & execution) introduces the first mutating tools and, with them, the graph node pair
that requests an approval mid-run and invokes the approved mutation — both riding the M7 gate. It also
brings stdio MCP child-process launching (scrubbed env) and per-server circuit breakers. The replay
capture (`llm_interactions`, `run_events`) and per-run/per-scope budgets carry through unchanged.
