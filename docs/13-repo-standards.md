# 13 — Repository & Open-Source Standards

This repo is a portfolio centerpiece: it must read like an actively maintained, enterprise-grade
OSS project within 30 seconds of landing on it. Every artifact below is specified here and
**created in M0** (they are scaffolding, not application code). Nothing is ever pushed by tooling —
pushes are done exclusively by the repository owner.

## 1. README specification

Order matters — recruiters scan top-down: logo/wordmark + one-line value prop → badges → 30-second
"what is this" with the **hero GIF** → feature grid → architecture diagram (the C4 container view,
Mermaid — renders natively on GitHub) → quickstart (`docker compose up` path, < 10 lines) → docs
map → benchmarks table (from the eval harness, with date + config) → roadmap link → security
posture summary → license + acknowledgements.

Badges (activate as they become real; **no fake badges — a lying badge is worse than none**):
CI · CodeQL · coverage (Codecov) · Python 3.12+ · TypeScript · license Apache-2.0 · SemVer ·
OpenSSF Scorecard (post-publish) · docs.

## 2. Community & governance files

| File | Content decision |
| --- | --- |
| `LICENSE` | **Apache-2.0.** Justification: explicit patent grant and contribution licensing (§5) matter for an AI/agents project more than MIT's brevity; NOTICE support; the license enterprises default-approve. MIT rejected as weaker on patents; GPL rejected as adoption friction contradicts portfolio goals. |
| `CONTRIBUTING.md` | Dev setup (devcontainer + manual), branch/commit conventions (below), PR checklist mirroring the milestone Definition of Done, eval re-bless procedure, ADR process for design changes |
| `CODE_OF_CONDUCT.md` | Contributor Covenant 2.1, contact = repo owner email |
| `SECURITY.md` | Private vulnerability reporting via GitHub Security Advisories; 90-day disclosure; supported-versions table; explicit scope note (sandbox escape reports especially welcome) |
| `CODEOWNERS` | `* @<owner>`; per-area entries (`/backend/src/spidey/execution/` etc.) to demonstrate the pattern even solo |
| `CHANGELOG.md` | Keep a Changelog format; `Unreleased` section maintained per milestone; releases cut from it |
| `.github/ISSUE_TEMPLATE/` | `bug_report.yml`, `feature_request.yml`, `eval_regression.yml` (custom — reinforces the eval story), `config.yml` routing security → private advisories |
| `.github/PULL_REQUEST_TEMPLATE.md` | Summary / linked issue / milestone DoD checklist (tests, docs, security review, eval impact) |
| `.github/dependabot.yml` | pip + npm + docker + github-actions ecosystems, weekly, grouped minor/patch |

## 3. Conventions

- **Commits:** Conventional Commits (`feat(codeintel): …`, `fix(sandbox): …`, `docs(adr): …`).
  Why: machine-readable history → automated CHANGELOG sections, and it reads professionally.
  History shape: **milestones land as small PR-sized commit series** (scaffold → domain → adapters
  → API → tests → docs), never one mega-commit per milestone; no fixup noise (`wip`, `oops`) in
  main history.
- **Branching:** trunk-based; short-lived `feat/m3-symbol-extraction`-style branches; `main` always
  green and releasable.
- **Versioning:** SemVer. 0.y.z during milestones (0.MINOR = milestone completion), `v1.0.0` at
  M15. Release flow: CHANGELOG finalize → tag → CI builds/signs images + SBOM → GitHub Release
  with generated notes + eval report snapshot. Releases drafted by CI, **published manually by the
  owner** (never auto-pushed).
- **Docs style:** every doc starts with a one-paragraph purpose; Mermaid for all diagrams (GitHub
  renders it — no binary image sources to bit-rot); relative links only; consistent heading depth;
  file names `NN-topic.md`; one docs linter in CI (markdownlint + link checker + Mermaid
  compile check).

## 4. GitHub operations

- **Labels:** `type:` bug/feature/docs/security/eval · `area:` per bounded context · `milestone:`
  M0–M15 · `good-first-issue`, `help-wanted` (aspirational but signals health).
- **Project board:** one "Spidey v1" board, columns Backlog → Milestone-ready → In progress →
  In review → Done; milestone tracker mirrors docs/04.
- **Discussions:** enable with categories Q&A, Ideas, Show-and-tell, Announcements — low cost,
  signals openness. Issues stay for defects/work items only.
- **Workflows** (`.github/workflows/`): `ci.yml` (lint → typecheck → test+coverage → build),
  `security.yml` (CodeQL, Semgrep, gitleaks, pip-audit/npm-audit, Trivy, SBOM — see doc 11 §3),
  `evals.yml` (T1 on PR, T2 nightly), `docs.yml` (markdownlint, links, Mermaid, OpenAPI export +
  diff comment), `release.yml` (tag-triggered: build, sign, SBOM, draft release). All actions
  SHA-pinned. **No workflow ever pushes commits or publishes without manual approval
  (environments + required reviewers).**

## 5. Developer experience

- **`.devcontainer/`**: yes — one-click reviewer experience in Codespaces/VS Code is exactly the
  audience this repo targets. Single container + docker-compose services, uv + Node 20 + Docker
  socket for sandbox dev; postCreate runs `make bootstrap`.
- **Pre-commit:** ruff (fix), pyright, gitleaks, markdownlint, conventional-commit-msg hook,
  eslint/prettier for `frontend/`.
- **Coverage:** pytest-cov + vitest coverage → Codecov; thresholds: domain/application ≥ 90 %,
  overall ≥ 85 %; badge in README; coverage delta comment on PRs.
- **OpenAPI:** exported spec committed at `docs/api/openapi.json` per milestone (CI verifies
  freshness); rendered reference via GitHub Pages later (post-v1, optional).

## 6. Demo assets plan (produced M12–M15, placeholders until then)

`docs/assets/` — hero GIF: full run (goal → plan → approval → diff → tests → PR) recorded with
**VHS** (terminal, scriptable = reproducible) + browser capture; per-feature GIFs: approval gate,
live dashboard, replay timeline, booby-trapped-repo containment (the security money-shot);
architecture PNG exports only where READMEs embed outside GitHub. Asset checklist tracked as
M12/M15 issues so "screenshots" never means "someday".
