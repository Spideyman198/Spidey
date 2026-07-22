# v1.0.0 Release Checklist

The sign-off gate for tagging `v1.0.0`. Every item is satisfied by an automated
gate or a committed artifact; the release is **drafted by CI on tag and published
by the owner**.

## Quality gates (green on `main`)

- [x] **Backend**: ruff format + check, pyright (strict), import-linter (11 contracts), pytest (unit + integration) at ≥ 85% coverage.
- [x] **Frontend**: tsc, ESLint, Vitest, build, `npm audit`.
- [x] **OpenAPI** spec fresh (`export_openapi.py --check`).
- [x] **Helm**: `helm lint` + `helm template` + Conftest policy (252 checks).
- [x] **Docs**: markdownlint (pinned).

## Security gates (SEC-*)

- [x] **SEC-\* matrix** complete — every requirement controlled and test-verified ([matrix](sec-verification-matrix.md)).
- [x] **SAST**: Bandit + Semgrep (`--error`), including the no-direct-file-IO invariant.
- [x] **CodeQL** `security-extended` on **python + javascript-typescript**.
- [x] **Secrets**: full-history gitleaks scan clean.
- [x] **Threat model** reviewed; [residual-risk register](threat-model-residual-risk.md) signed, no blocking risk.

## Supply chain (SEC-SUP)

- [x] **Dependency audit**: `pip-audit --strict` against the frozen lockfile.
- [x] **License gate**: backend (186 deps) + frontend within [policy](license-policy.md); no GPL/AGPL/SSPL.
- [x] **SBOM**: CycloneDX generated for the repo and the release image.
- [x] **Signing**: Cosign keyless (GitHub OIDC) signs the release image archive and its SBOM.
- [x] **Trivy**: filesystem + IaC scan (CRITICAL/HIGH) clean.
- [x] **Dependabot** + hash-pinned lockfile; reranker model hash-pinned.

## Success criteria (docs/01 §8)

- [x] **Criterion 1** — end-to-end plan→edit→test→approve→PR ([evidence](success-criteria.md)).
- [x] **Criterion 2** — booby-trapped repo contained, attempts audited ([evidence](success-criteria.md)).
- [x] **Criterion 3** — evaluation harness reports success/cost/latency in CI ([evidence](success-criteria.md)).

## Release mechanics

- [x] Version bumped to `1.0.0` (`backend/pyproject.toml`, chart `appVersion`).
- [x] `CHANGELOG.md` finalized: `[1.0.0]` section dated, links updated.
- [x] `README.md` status → v1.0.
- [ ] **Owner action**: tag `v1.0.0` (`git tag -s v1.0.0 && git push --tags`) — the
      [release workflow](../../.github/workflows/release.yml) builds, SBOMs, signs,
      and drafts the GitHub release.
- [ ] **Owner action**: review the drafted release notes and **publish**.

The two unchecked items are the owner's by design — Spidey never tags, pushes, or
publishes on its own.
