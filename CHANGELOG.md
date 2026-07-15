# Changelog

All notable changes to this project are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html). Pre-1.0, each completed
milestone bumps the minor version (`0.MINOR.z` = milestone number).

## [Unreleased]

### Added

- Complete v1.0 architecture: requirements & threat model, C4 diagrams, 14 ADRs, bounded-context
  design, milestone plan M0–M15, and specialist designs for the MCP tool plane, retrieval, memory,
  events & replay, observability, evaluation, security, and deployment (`docs/`).
- M0 foundations: repository scaffolding, community & governance files, CI/security pipeline,
  Docker Compose stack, configuration & structured logging & telemetry kernel, FastAPI walking
  skeleton with health endpoints, Celery heartbeat, Alembic baseline, and the evaluation harness
  skeleton with tiered CI wiring.
- M1 identity, audit & sessions: Argon2id users; HS256 access tokens with rotating,
  reuse-detecting refresh tokens; RBAC (admin/developer/viewer) enforced per route; Redis
  token-bucket rate limiting and per-account lockout (fail-closed); an append-only `audit_log`
  (database-trigger enforced) with an independent-commit sink for denial evidence; session and
  message CRUD with strict owner scoping; first-run admin bootstrap CLI; and the full versioned
  REST surface under `/api/v1` with OpenAPI. Backed by 143 tests (unit, integration, attack-shaped
  security) at ~90% coverage.
- M2 workspaces & repository ingestion: `SafeFileSystem` two-layer containment (pure path policy +
  symlink/NTFS-junction resolution) as the single guarded file-access path; local-path and
  GitHub-PAT ingestion on Celery workers with durable status transitions; envelope-encrypted PAT
  storage (HKDF + AES-256-GCM); SSRF-guarded clone (HTTPS + host allow-list + private-address
  rejection); `.gitignore`-aware, binary- and size-capped file manifests with SHA-256 change
  detection; per-workspace disk quotas; and owner-scoped workspace APIs. Backed by 224 tests
  (adds SEC-FS junction/symlink/traversal, SSRF, and envelope-encryption attack suites) at ~89%
  coverage.
- M3 parsing & code index: Tree-sitter parsing for Python, JavaScript, TypeScript, Go, Java, and
  Rust via a pluggable language registry; symbol extraction (functions, classes, methods,
  interfaces/structs/enums/traits, imports) with dotted qualified names into a `symbols` index;
  a non-overlapping, header-path-aware chunker feeding M4 embedding; incremental re-indexing driven
  by the M2 SHA-256 manifest (only changed files re-parsed, deleted files removed); resource-bounded
  parsing (wall-clock timeout, size cap, depth limit); ingestion now chains code indexing; and
  owner-scoped symbol/index-status APIs. Backed by 261 tests (adds per-language extraction and
  incremental-index suites) at ~90% coverage. Runtime image now includes git for cloning.
