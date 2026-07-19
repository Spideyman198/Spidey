"""Long-term memory domain (M11, docs/07 §2).

Five typed record kinds behind one schema and one recall API. A ``Memory`` is a
durable, attributed fact the system distilled from a run — never an instruction.
Scope (``workspace_id`` / ``user_id``) is a *hard* recall boundary, and content
is treated as untrusted even at read time (defense in depth against a gate
bypass): the domain models carry the data; the write gate and recall framing
enforce the safety invariants.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class MemoryKind(StrEnum):
    """The five typed kinds (docs/07 §1). Only ``SEMANTIC`` crosses repositories."""

    REPOSITORY = "repository"  # facts about one workspace's code
    SEMANTIC = "semantic"  # cross-repo engineering knowledge (no repo-identifying content)
    PROCEDURAL = "procedural"  # playbooks: action sequences that worked
    EPISODIC = "episodic"  # what happened on a specific run
    EVALUATION = "evaluation"  # graded outcomes (kind already used by the eval store)


# Kinds whose recall must never cross a workspace boundary (docs/07 §4).
WORKSPACE_SCOPED_KINDS = frozenset(
    {MemoryKind.REPOSITORY, MemoryKind.PROCEDURAL, MemoryKind.EPISODIC}
)


class MemoryScope(BaseModel):
    """The hard recall boundary. A workspace-scoped memory recalls only within
    that workspace; a user-scoped memory only for that user."""

    model_config = ConfigDict(frozen=True)

    workspace_id: uuid.UUID | None = None
    user_id: uuid.UUID | None = None


class MemoryProvenance(BaseModel):
    """Where a memory came from — for attribution at recall and for audit."""

    model_config = ConfigDict(frozen=True)

    run_id: uuid.UUID | None = None
    distilled_by: str = "distiller"  # "distiller" | "user"
    source_refs: list[str] = Field(default_factory=list[str])


class MemoryCandidate(BaseModel):
    """A proposed memory, before the write gate. Distillation (or an explicit
    user 'remember this') produces these; only the gate turns them into records."""

    model_config = ConfigDict(frozen=True)

    kind: MemoryKind
    content: str
    scope: MemoryScope = Field(default_factory=MemoryScope)
    provenance: MemoryProvenance = Field(default_factory=MemoryProvenance)
    confidence: float = Field(default=0.6, ge=0.0, le=1.0)


class Memory(BaseModel):
    """A stored long-term memory record (docs/07 §2)."""

    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    kind: MemoryKind
    scope: MemoryScope
    content: str
    provenance: MemoryProvenance
    confidence: float = Field(ge=0.0, le=1.0)
    use_count: int = 0
    last_used_at: datetime | None = None
    created_at: datetime
    expires_at: datetime | None = None
    superseded_by: uuid.UUID | None = None

    @property
    def active(self) -> bool:
        return self.superseded_by is None


class RecalledMemory(BaseModel):
    """A memory returned by recall, with its similarity to the query."""

    model_config = ConfigDict(frozen=True)

    memory: Memory
    similarity: float


# ── confidence feedback (docs/07 §3) ──────────────────────────────────────────
_REINFORCE_FACTOR = 0.2
_DECAY_FACTOR = 0.5
_PRUNE_BELOW = 0.15  # confidence under which a memory is eligible for eviction


def reinforce(confidence: float) -> float:
    """A run that used this memory succeeded — move confidence toward 1.0
    asymptotically (never a hard jump, so one success cannot bless a lie)."""
    return round(min(1.0, confidence + (1.0 - confidence) * _REINFORCE_FACTOR), 4)


def decay(confidence: float) -> float:
    """A run that used this memory failed — halve confidence. Poisoned or stale
    memories die from evidence, not just curation (docs/07 §3)."""
    return round(max(0.0, confidence * _DECAY_FACTOR), 4)


def prunable(confidence: float) -> bool:
    return confidence < _PRUNE_BELOW
