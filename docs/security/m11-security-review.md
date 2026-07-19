# M11 Security Review — Long-Term Memory

**Date:** 2026-07-20 · **Scope:** the memory write gate, `MemoryService` (write / recall / feedback /
delete), the distiller, scope isolation, recall framing, and the memory management API · **Verdict:
PASS**

> The defining risk of long-term memory is **injection persistence**: if an agent — or repository
> content that reached an agent — could write an imperative into memory, that imperative would recur
> across every future session. M11 is engineered so a memory is a *fact, never an instruction*, and
> so memory content is treated as untrusted even at read time.

## 1. Controls implemented and verified this milestone

| Control (requirement) | Implementation | Verification |
| --- | --- | --- |
| A memory is a fact, not a command | The write gate rejects anything that trips the injection screen or the imperative-shape screen; there is no code path from a candidate to storage that bypasses it | `test_memory_domain` imperative rejection; `test_memory_poisoning` corpus |
| Agents cannot write memory mid-run | Only end-of-run **distillation** and the explicit user "remember this" produce candidates; the graph exposes no write; recall is read-only | `MemoryDistiller` is the only automatic writer; `test_memory_distiller` |
| Secrets/PII never land in memory | The gate scrubs content **before** storage (redaction, not rejection), so a secret-shaped value is never written raw | `test_memory_domain` secret-scrub case |
| Scope is a hard recall boundary | `semantic` (cross-repo) memories may carry no workspace scope; workspace kinds must name their workspace; recall is **double-filtered** (store candidate pool + vector search) | `test_memory_service` cross-workspace isolation; gate scope rules |
| Recalled memory is inert, attributed data | `frame_memories` renders recall as untrusted observations with confidence/run attribution, never as instructions — same inert framing as retrieved code (docs/07 §4) | `test_memory_domain` framing case |
| Poison dies from evidence | Confidence reinforces on a successful run and decays (halves) on failure; low-confidence memories become prunable | `test_memory_domain` feedback; `MemoryService.record_feedback` |
| User sovereignty (FR-5.3) | Owner-scoped list/create/delete; **delete removes the record and the vector**; the "remember this" write still passes the gate | `test_memory_service` delete-removes-both; `memories` API |
| Poisoning corpus stays inert (exit) | A corpus of imperatives, injections, secrets, and cross-scope leaks is graded by the memory-safety suite; a single leak fails the suite | `test_memory_poisoning` containment 1.0 |

## 2. Design decisions with security weight

- **One write door, and agents don't hold the key.** Every long-term write goes through the gate,
  and the only callers are distillation and explicit user teaching — never an agent mid-run. This is
  what stops memory from becoming a durable injection channel.
- **Defense in depth on scope and on content.** Scope is enforced at the gate (write time) *and* at
  both the store and the vector index (read time); content is scrubbed at write *and* framed as
  untrusted at read. A single failure on either axis does not leak.
- **Truth by evidence, not by assertion.** Confidence is asymptotic on reinforcement (one success
  can't bless a lie) and halves on failure, so a poisoned or stale memory decays out of usefulness
  even if it somehow passed the gate.
- **Cross-repo is the only shared kind, and it is scrubbed of identity.** Only `semantic` memories
  cross workspaces, and the gate forbids them a workspace scope — repository/procedural/episodic
  knowledge stays inside its workspace.

## 3. Accepted findings / deliberate scoping

- **Distillation and recall use live embeddings/models.** The gate, feedback, framing, scope
  isolation, delete, and poison-containment are all proven offline with fakes; the Qdrant index and
  the fastembed embedder are exercised in integration, like the M4 retrieval path.
- **Imperative detection is heuristic.** The gate combines the injection screen with an
  imperative-shape regex; it favors rejecting a borderline fact over admitting a borderline command.
  Confidence decay is the backstop for anything that slips through.
- **Eviction is confidence-driven; a scheduled pruner is later.** `prunable()` marks low-confidence
  records; a background sweep that deletes them (record + vector) is a maintenance-task follow-on.
- **No memory events on the SSE timeline yet.** Distillation writes are audited via the store; a
  dedicated `memory.*` event stream is deferred to the M12 dashboard work.

## 4. Attack-shaped / robustness tests added

Write gate: imperative/injection rejection, secret scrub-before-store, semantic-must-not-be-scoped,
workspace-kind-requires-scope, dedupe; service: cross-workspace recall isolation, gate-rejected
candidates never stored, delete removes record *and* vector, reinforce/decay; distiller: imperatives
dropped, workspace vs semantic kind assignment; and the full memory-poisoning corpus contained at 1.0.

## 5. Carry-forward

M12 surfaces memory in the dashboard (inspect/delete UI) and can add the `memory.*` event stream and
the scheduled low-confidence pruner. Recall currently informs the planner; extending attributed
recall to the coder/reviewer prompts is a straightforward follow-on behind the same framing.
