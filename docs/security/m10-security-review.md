# M10 Security Review — Debugger, Documenter & PR Delivery

**Date:** 2026-07-19 · **Scope:** the run-graph tail (test → debug → document → PR), the native
GitHub PR flow (`PrService` + `GitHubPrProvider` + `push_branch`), the run report, and the
agent-task/groundedness eval suites · **Verdict: PASS**

## 1. Controls implemented and verified this milestone

| Control (requirement) | Implementation | Verification |
| --- | --- | --- |
| No PR without a human gate | The graph opens a PR only after the durable `pr_gate` interrupt resolves; `open_pr` is unreachable before it, and the gate exists only when PR delivery is configured | `test_m10_flow` (PR opened only past the second resume); `route_after_document` |
| PR token never leaks | The access token is decrypted in-memory, injected only into the push URL and the `Authorization` header, and scrubbed from every error/log path; the API host is fixed to `api.github.com` (no SSRF from the stored URL) | `test_pr` (token in header not payload; non-GitHub host rejected); `github_pr` / `push_branch` scrub-on-error |
| Push stays on the allow-list | `push_branch` validates the remote against the same clone allow-list before any network call | `GitPythonProvider.push_branch` → `validate_clone_url` |
| Debug loop cannot run away | A failing test routes to the debugger at most `_MAX_DEBUG_ROUNDS` times, then escalates to `needs_human`; the fix rides the **same approval-gated** coder/commit path — no new un-gated write appears | `test_m10_flow` (bounded retry → pass); `route_after_test` escalate branch |
| Untrusted output stays data | The Debugger and Documenter receive test output and diffs framed as untrusted data, never instructions; test output was already sandbox-bounded and secret-scanned (B4r, M9) | `_DEBUG_SYSTEM` / `_DOC_SYSTEM` prompts; M9 tester output path |
| Run report is a read-only projection | `build_run_report` is a pure function over the run record, plan, and durable event timeline; the endpoint is owner-scoped via `RunService` | `test_report`; `GET /runs/{id}/report` owner guard |
| PR opening is audited | `PrService` writes a `PULL_REQUEST_OPENED` audit record with the actor, workspace, and PR number | `test_pr` (audit recorded) |

## 2. Design decisions with security weight

- **The dangerous half is native and gated.** PR creation is not delegated to an external MCP server
  (docs/05): the human gate, the token handling, and the audit trail are in-process code, so the
  approval invariant holds at the same choke point as the rest of the run.
- **Debugging adds no new authority.** The debugger cannot write; it appends a plan step and the
  *coder* proposes the edit, which still passes the M7 approval gate and the M8 secret scan. A fix is
  therefore exactly as gated as any other edit — the loop adds retries, not privilege.
- **Bounded everywhere.** The fix-retry loop is bounded like the review loop and the step budget;
  exhaustion escalates to a human rather than shipping a broken or unbounded change (NFR-5).
- **Reports are projections, not a second source of truth.** The run report is rebuilt from the
  event timeline, so it cannot drift from what actually happened or introduce a new write path.

## 3. Accepted findings / deliberate scoping

- **Live PR + push are network paths, exercised with real credentials only.** Offline tests cover
  parsing, gating, token handling, and error paths with fakes; the live GitHub round-trip runs when a
  token is configured, like the T2 LLM conformance suites.
- **Eval suites are T2 and grade supplied results.** The agent-task and groundedness metrics are
  pure and unit-tested; the first success-rate baseline (`evaluation/baselines/agent_tasks.json`,
  floor 0.5) is a committed starting point to be re-blessed as live runs accumulate.
- **`--force-with-lease` on the run branch.** The push updates only the run's own `spidey/run-<id>`
  branch (never a user branch), so a lease-guarded force is safe and avoids stale-ref failures on
  resume.
- **Egress proxy for installs** remains M-later (carried from M9); PR delivery needs only the fixed
  `api.github.com` host and the repo's own remote.

## 4. Attack-shaped / robustness tests added

PR flow: non-GitHub host rejected, missing token refused, non-201 response raised as a safe error,
token confined to the Authorization header (never the payload), local-source workspace has nothing to
deliver; graph: failing tests bounded-retry through the debugger then escalate, and a PR opens only
past the human gate; report: owner-scoped projection of the timeline.

## 5. Carry-forward

M11 (long-term memory) adds the memory write gate and a memory-poisoning eval. The egress-proxy
adapter and the gVisor sandbox upgrade remain the open execution items behind their seams.
