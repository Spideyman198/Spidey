# M8 Security Review

**Date:** 2026-07-17 · **Scope:** diff-based edit tools over `SafeFileSystem`
(`workspace.read_file` / `workspace.apply_edit`), secret detection on write paths
(`platform.security.secrets`), branch-per-run git workflow (`GitProvider` local ops +
`GitWorkflowService`), the coder → edit-approval gate → apply → reviewer-loop → commit graph, and
the run diff API · **Verdict: PASS**

## 1. Controls implemented and verified this milestone

| Control (requirement) | Implementation | Verification |
| --- | --- | --- |
| Edits contained to the workspace (SEC-FS) | Every path flows through `SafeFileSystem`: layer-1 pure path policy screens the *attempt* (traversal/absolute/drive → explicit denial), layer-2 resolution catches symlink/junction escapes on the actual operation; the workspace id comes from the trusted `ToolContext`, never from tool arguments | `test_code_edit` traversal read + write denials; M2 SEC-FS suites unchanged |
| No mutation without a human grant | `workspace.apply_edit` is `SideEffect.WRITE`; the M7 registry invariant applies unchanged — denied without a resolved `Approval` for exactly that tool and run. Proposals are *recorded before the pause* by the coder node; `apply_edits` re-fetches each approval and the registry re-validates it (defense in depth) | `test_code_edit` registry-gate cases (denied bare, allowed with matching grant, RBAC precedes grant); `test_coder_workflow` end-to-end gates |
| Secrets never reach disk, context, or history (SEC-SECRETS) | New `scan_for_secrets` (high-confidence shapes: provider tokens, key blocks, URL/bearer creds, password assignments) runs **twice**: on the edit's unified diff *before the write*, and on the step diff *before the commit*. A hit is a typed refusal; findings carry kind + line, never the matched value | `test_secrets` (13 cases incl. never-echoes-value); `test_code_edit` blocked-before-write; `test_git_workflow` blocked commit leaves HEAD at baseline |
| Run isolation in git | Every run works on `spidey/run-<id>`; the user's branch is never mutated. All git ops are workspace-local — **no push exists in this milestone**, so nothing the agent does can leave the machine. Commit identity is repository-local (`Spidey Agent`), never the user's global config | `test_git_provider` / `test_git_workflow` branch + identity cases |
| Atomic, attributable steps | One conventional commit per reviewed step (`feat(run): …` + run/step trailer); a clean tree never produces an empty commit; the commit and its `step_committed` event share the sha for replay | `test_git_workflow` message/atomicity; `test_coder_workflow` single net commit |
| Bounded review loop | Reviewer critique loops the coder at most `_MAX_REVIEW_ROUNDS` (2) times per step, then proceeds — an adversarial or broken reviewer cannot spin the run (NFR-5 complements the per-run budget) | `route_after_reviewer` bound; `test_coder_workflow` two-round repair |
| Reviewer treats the diff as data | The reviewer prompt frames the diff as untrusted input, and its only *effect* is routing (approve/critique) — a prompt-injected diff cannot invoke tools or approve itself; mutations still require the human gate | `_REVIEW_SYSTEM`; graph topology (reviewer has no tool access) |
| Owner-scoped diff surface | `GET /runs/{id}/diff` resolves the run owner-scoped first (non-owner → 404) and reads only that run's workspace against its recorded `base_commit` | Route mirrors the timeline endpoint's guard order |

## 2. Design decisions with security weight

- **Two independent secret gates.** The edit-time scan stops a credential before it exists on disk;
  the commit-time scan stops anything that slipped past (e.g., a secret assembled across multiple
  edits) from entering git history — where removal is expensive and leak-prone. Both gates refuse;
  neither redacts-and-continues, because a laundered secret in a repo is still an incident.
- **The coder proposes; it never executes a write.** Write-shaped tool calls are converted to
  recorded `Approval` rows *by construction* in the coder node — the model's output cannot reach
  `registry.invoke` for a mutation on any path that skips the human. The M7 invariant did the
  gating; M8 adds the only legitimate route through it.
- **Filesystem stays native (ADR-0008/0010).** Containment and diff scanning are our invariants;
  serving edits through an external MCP filesystem server would move them outside the choke point.
  `workspace.*` tools are served *over* MCP, never replaced by one.
- **Exact-match edits, not free-form writes.** `apply_edit` replaces one unique occurrence (or
  creates a new file); the returned artifact *is* the unified diff. Reviewability is a security
  property here: the human approving and the reviewer critiquing see precisely what changes.
- **No network in the git workflow.** `ensure_repo`/`ensure_branch`/`commit_all`/`diff` cannot
  touch a remote; pushing/PR delivery is a later milestone with its own explicit human gate
  (docs/02 §5 `gate2`).

## 3. Accepted findings / deliberate scoping

- **Convention context is prompt-directed in this slice.** The coder is instructed to read files
  before editing and match their conventions, and the reviewer enforces consistency; a richer
  assembled convention profile (imports/style mined from codeintel) lands with context assembly
  work in M10. No security impact — reads are already gated and framed.
- **Secret detection is pattern-based.** High-confidence shapes only (gitleaks-style); entropy
  scanning was deliberately excluded to keep false-positive-driven refusals rare. The commit gate
  plus M6 capture-scrubbing bound the blast radius of a novel token shape.
- **Review-loop exhaustion proceeds to commit.** After the bounded rounds, the step commits with
  the critique in the transcript rather than pausing — the human sees every diff at the approval
  gate *before* it is applied, so nothing uncommitted-by-review lands without having been granted.
  M9's tester adds the behavioral check the reviewer cannot provide.
- **`_MAX_TOOL_ROUNDS`/`_MAX_REVIEW_ROUNDS` are code constants,** not Settings, until someone needs
  to tune them per deployment.
- **stdio MCP child-process launching + per-server circuit breakers** remain deferred (carried from
  M6/M7; the sandbox milestone M9 is their natural home).
- **Actions still tag-pinned** (carried from M0 §3; scheduled M15).

## 4. Attack-shaped / robustness tests added

Traversal read and traversal write through the edit tool (both denied, nothing written); planted
Anthropic-key edit blocked before the write with the value never echoed; planted key in a step diff
blocking the commit with HEAD provably unchanged; write tool denied bare / with a pending grant /
with another tool's grant / with another run's grant / to a viewer even with a grant; ambiguous and
missing exact-matches rejected; the full offline exit-criterion pair — scoped change landing on the
isolated branch, and the planted bad edit caught by the reviewer and repaired by the critique-fed
coder retry.

## 5. Carry-forward

M9 (sandboxed execution) is **the security-critical milestone**: hardened container image, network
`none`, non-root, read-only rootfs, cgroup caps, `CommandPolicy` argv allow-list, egress proxy for
approved installs, env scrub + output secret-scan — with the booby-trapped-repo red-team suite and a
published report. The M8 edit/commit gates carry through unchanged; the Tester gains the ability to
*run* what the Coder wrote, inside the sandbox boundary.
