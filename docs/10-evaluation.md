# 10 — Evaluation Framework

Evaluation exists from day one (module skeleton + CI wiring in M0) and grows with each milestone —
it is the regression gate for every prompt, model, retrieval, and graph change. Design goal:
**every quality claim in this project is a number with a trend line, not an adjective.**

## 1. Architecture

```
backend/src/spidey/evaluation/       # code: a bounded context like any other
  domain/        # Task, Suite, Grade, Metric, EvalRun — typed results model
  application/   # runners (live | replay-fixture), graders, metric computers, report builder
  infrastructure/# dataset loaders, sandbox grading executor, eval-store (PG), report writers
evaluation/                          # data & config: no code
  datasets/      # task definitions (YAML + fixtures), pinned repo refs (commit SHAs)
  baselines/     # blessed metric baselines per suite (JSON, versioned in git)
  reports/       # generated (gitignored)
```

Eval results persist to `eval_runs` / `eval_task_results` (the "evaluation memory" of doc 07),
graphed in Grafana, compared against `baselines/` in CI.

## 2. Suites

| Suite | What it measures | Grading | Key metrics |
|---|---|---|---|
| **codegen** (HumanEval-style) | Isolated function synthesis | Hidden tests executed in the sandbox | **pass@1, pass@k**, tokens/task |
| **retrieval** | Search quality on pinned repos | Golden queries → expected files/symbols | **precision@k, recall@k, MRR**, latency |
| **agent-tasks** (SWE-bench-style) | End-to-end: issue → patch on pinned real repos | Repo's own test suite (fail→pass) in sandbox + rubric checks (scope, diff size) | **success rate**, steps/run, wall-clock, **cost/task** |
| **groundedness** | Hallucination: are claims about the codebase supported? | Claims must cite retrieved provenance; LLM-judge with rubric + periodic human audit of judge agreement | grounded-claim rate, citation validity |
| **safety** | Prompt-injection & poisoning resistance | Attack corpus (injected README/code/comments/memories/MCP descriptions); grade = agent did NOT comply, DID flag | attack success rate (target 0 on known corpus), detection rate |
| **regression-replay** | Behavioral drift | Golden re-execution of recorded runs with LLM fixtures (doc 08 §5) | decision-sequence match, diff equivalence |
| **latency/perf** | NFR-2 budgets | Benchmarked search & indexing paths, agent step overhead | p50/p95 per operation |

Suite construction notes: agent-tasks starts as **hand-curated tasks on 2–3 pinned OSS repos**
(known-good, licensed) and adds a SWE-bench-lite subset post-v1 — running full SWE-bench is a
compute project in itself and is explicitly out of v1 scope. LLM-judge is used only where
execution-based grading is impossible (groundedness), always with a versioned rubric and a human
agreement spot-check, because judges drift.

## 3. Metrics model

Every eval run records: suite, task id, model + provider, prompt-pack version, config hash, git
SHA, outcome, grade detail, tokens (in/out), **cost USD**, latency, and replay ref. Cost and token
tracking reuse the LLM gateway metering — evals measure the same pipeline production uses.

## 4. CI integration (three tiers)

| Tier | Trigger | Contents | Budget | Gate |
|---|---|---|---|---|
| **T1 smoke** | every PR | regression-replay (fixtures, no LLM calls) + retrieval suite + unit-graded codegen subset with stub model | $0, < 5 min | hard fail on regression vs baseline |
| **T2 nightly** | schedule | full retrieval + codegen (live model) + agent-tasks subset + groundedness + safety corpus | capped $ budget, alerts on overrun | trend report; auto-issue on metric drop > threshold |
| **T3 release** | tag / manual | everything incl. full agent-tasks + comparative re-runs vs previous release | approved budget | release checklist item |

Baselines are updated only by explicit "re-bless" commits touching `evaluation/baselines/` — a
reviewed decision, never automatic. The T1 tier is deliberately **LLM-free** so PR CI is
deterministic, fast, and free; live-model judgment lives in T2/T3 where nondeterminism and spend
are managed. (This split is the answer to "evaluation should be part of CI" without making CI
flaky and expensive — the classic failure mode of naive LLM-in-CI setups.)

## 5. What evals gate (explicit list)

Prompt-pack changes (T1 replay must pass or be re-blessed) · model/provider routing changes (T2
comparative) · retrieval changes incl. v2 features rerank/compression (retrieval suite must show
the win that justifies them) · graph/topology changes (agent-tasks subset) · LangGraph/SDK
upgrades (full T2) · security-relevant prompt hardening (safety suite must not regress).
