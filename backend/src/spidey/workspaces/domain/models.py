"""Workspaces domain model."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

WORKSPACE_NAME_MAX = 100
# A GitHub PAT is opaque; cap length to bound storage and reject junk early.
TOKEN_MAX = 512


class RepositorySource(StrEnum):
    LOCAL = "local"
    GITHUB = "github"


class WorkspaceStatus(StrEnum):
    PENDING = "pending"  # created, not yet ingested
    INGESTING = "ingesting"  # clone/copy + manifest in progress
    READY = "ready"  # ingested and inventoried
    FAILED = "failed"  # ingestion failed (see error)


class Workspace(BaseModel):
    """A managed, isolated repository workspace. ``root`` never crosses the
    configured workspaces base directory (SEC-FS)."""

    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    owner_id: uuid.UUID
    name: str
    source: RepositorySource
    location: str  # local path (as provided) or GitHub URL
    branch: str | None
    status: WorkspaceStatus
    head_commit: str | None
    size_bytes: int
    file_count: int
    error: str | None
    created_at: datetime
    updated_at: datetime


class IngestionRequest(BaseModel):
    """Validated inputs for ingesting a repository into a new workspace.

    The raw token is transient input — it is envelope-encrypted before storage
    and never surfaces in a domain entity, log, or API response.
    """

    model_config = ConfigDict(frozen=True)

    name: str = Field(min_length=1, max_length=WORKSPACE_NAME_MAX)
    source: RepositorySource
    location: str = Field(min_length=1, max_length=2048)
    branch: str | None = Field(default=None, max_length=255)
    token: str | None = Field(default=None, max_length=TOKEN_MAX, repr=False)


class FileManifestEntry(BaseModel):
    """One file's identity for change detection and indexing eligibility.

    ``sha256`` drives incremental re-ingestion (FR-1.3): unchanged files keep
    their hash across syncs and are skipped by later indexing.
    """

    model_config = ConfigDict(frozen=True)

    path: str  # workspace-relative, forward-slashed
    sha256: str
    size_bytes: int
    is_binary: bool
    indexable: bool  # text and within the per-file size cap
