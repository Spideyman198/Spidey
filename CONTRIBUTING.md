# Contributing to Spidey

Thanks for your interest. This project is developed in reviewed milestones with a strict
Definition of Done — the process below applies to the maintainer's own changes too.

## Development setup

**Option A — devcontainer (recommended):** open the repo in VS Code / Codespaces and accept the
devcontainer prompt. Everything (Python 3.12, uv, Node 20, Docker-in-environment) is provisioned;
`make bootstrap` runs automatically.

**Option B — manual:**

```bash
# Requirements: Python 3.12+, uv, Docker (for the service stack), Node 20+ (frontend, from M12)
git clone <repo> && cd spidey
cp .env.example .env
make bootstrap          # uv sync + pre-commit install
make dev                # start the full compose stack
make test               # unit tests (integration tests skip if services are down)
```

Windows without `make`: the Makefile targets are thin wrappers — the underlying commands are listed
in the [Makefile](Makefile) and run fine in PowerShell (e.g. `python -m uv sync` inside `backend/`).

## Workflow

1. **Branch** from `main`: `feat/m3-symbol-extraction`, `fix/sandbox-timeout`, `docs/adr-0015`.
2. **Commit** using [Conventional Commits](https://www.conventionalcommits.org/):
   `feat(codeintel): extract call references from tree-sitter AST`.
   Small, meaningful commits — a reviewer should be able to follow the history commit by commit.
3. **Open a PR** even when working solo; fill in the template checklist (tests, docs, security,
   eval impact). `main` is protected: CI must be green, history stays linear (squash or rebase —
   no merge commits).
4. **Never push directly to `main`.** Releases are drafted by CI on tags and published manually by
   the owner.

## Quality gates (all enforced in CI)

| Gate | Command |
| --- | --- |
| Lint + format | `make lint` (ruff check + format check) |
| Types (strict) | `make typecheck` (pyright) |
| Tests + coverage | `make test` (thresholds: domain/application ≥ 90 %, overall ≥ 85 %) |
| Architecture boundaries | import-linter contracts (runs inside `make lint`) |
| Security | `make security` (bandit, semgrep, pip-audit, gitleaks) |
| Docs | markdownlint + link check |

## Architectural changes

The v1.0 architecture is frozen ([docs/14-design-review.md](docs/14-design-review.md)). A change to
a frozen decision requires a new ADR that supersedes the old one, justified by a critical flaw —
open an issue first. New code must respect the structure rules in
[docs/03-repository-structure.md](docs/03-repository-structure.md) (they are CI-enforced).

## Evaluation baselines

If your change affects agent behavior, retrieval quality, or prompts, run the relevant suite
(`make eval TIER=t1`) and either keep baselines green or include a reviewed re-bless commit
updating `evaluation/baselines/` with justification in the PR description.

## Reporting security issues

Privately, please — see [SECURITY.md](SECURITY.md).
