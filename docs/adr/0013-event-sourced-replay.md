# ADR-0013: Event-sourced replay with content-addressed artifacts

**Status:** Accepted · 2026-07-09

## Context

Every execution must be replayable: prompts, responses, tool invocations, events, diffs, token
usage, latency, costs, failures. Replay serves three masters: debugging ("why did it do that?"),
regression testing (behavioral drift gates in CI), and the dashboard/timeline UI.

## Decision

Runs are **event-sourced as a byproduct of ADR-0011**: the persisted `run_events` stream is the
replay spine. Large bodies (prompts/responses in `llm_interactions`, diffs, tool outputs,
artifacts) are stored **content-addressed (SHA-256)** on a local volume behind an `ArtifactStore`
port (S3-compatible adapter later), referenced by hash from events. Redaction (secrets, PII)
happens **at capture time** — sensitive data never lands in the replay store. Three replay modes:
timeline reconstruction (UI renders live and historical runs through the same event reducer),
golden re-execution (recorded LLM/tool results played back as fixtures — the deterministic CI
regression tier), and comparative re-run (same goal, new config, eval-harness diffed). Full-fidelity
bodies expire on a retention window (default 30 days); events, episodic summaries, and metrics are
kept.

## Alternatives considered

- **Full event-sourcing as the write model** (state = fold(events)) — maximal purity; makes every
  CRUD path harder and the ORM an enemy. Rejected: we event-source the *run narrative*, not the
  application's entire state.
- **LangSmith / Langfuse for traces & replay** — good products; but replay is core to our CI story
  and portfolio narrative, and shipping conversation data to a third party conflicts with the
  self-hosted posture. Langfuse self-hosted noted as an optional exporter later. Rejected as the
  system of record.
- **Blob-per-run JSON dumps** — trivial to write, useless to query, no dedupe, no partial
  retention. Rejected.

## Consequences

- (+) Replay, timeline, audit, and eval fixtures are one storage design, not four features.
- (+) Content addressing dedupes repeated prompts/diffs across runs materially.
- (−) Capture-time redaction means unredacted data is unrecoverable by design — accepted: that is
  the security property, and raw debugging uses live traces within their short retention.
- (−) Fixture playback must handle nondeterministic tool results (timestamps, ordering) →
  normalization rules live with the fixtures and are versioned.
