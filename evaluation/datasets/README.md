# Evaluation datasets

Task definitions and fixtures for the benchmark suites (docs/10). Data only — suite code lives in
`backend/src/spidey/evaluation/`.

Layout (populated as suites land):

- `retrieval/` — golden queries → expected files/symbols against pinned repos (M4)
- `codegen/` — HumanEval-style tasks with hidden tests (M7)
- `replays/` — recorded run fixtures for the deterministic T1 regression tier (M7)
- `agent-tasks/` — issue → patch tasks on pinned repo SHAs (M10)
- `safety/` — prompt-injection & poisoning attack corpus (M11)

Rules: every dataset pins exact upstream commit SHAs, carries a `manifest.yaml` (source, license,
grading method), and never contains live credentials or PII.
