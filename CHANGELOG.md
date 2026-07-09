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
