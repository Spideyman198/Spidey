"""Code-index persistence models. Schema owned by Alembic migration 0003."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from spidey.platform.db import Base


def _utcnow() -> datetime:
    return datetime.now(tz=UTC)


class IndexSnapshotRecord(Base):
    """One row per workspace: the current state of its code index."""

    __tablename__ = "index_snapshots"

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True
    )
    status: Mapped[str] = mapped_column(String(16), default="pending")
    file_count: Mapped[int] = mapped_column(Integer, default=0)
    symbol_count: Mapped[int] = mapped_column(Integer, default=0)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )


class IndexedFileRecord(Base):
    """The SHA-256 of each file as last indexed — drives incremental re-index."""

    __tablename__ = "indexed_files"
    __table_args__ = (UniqueConstraint("workspace_id", "path", name="uq_indexed_files_ws_path"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    path: Mapped[str] = mapped_column(String(4096))
    sha256: Mapped[str] = mapped_column(String(64))
    language: Mapped[str] = mapped_column(String(16))


class SymbolRecord(Base):
    __tablename__ = "symbols"
    __table_args__ = (
        Index("ix_symbols_ws_path", "workspace_id", "path"),
        Index("ix_symbols_ws_name", "workspace_id", "name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    path: Mapped[str] = mapped_column(String(4096))
    language: Mapped[str] = mapped_column(String(16))
    kind: Mapped[str] = mapped_column(String(16))
    name: Mapped[str] = mapped_column(String(512))
    qualified_name: Mapped[str] = mapped_column(String(1024))
    parent: Mapped[str | None] = mapped_column(String(1024))
    start_line: Mapped[int] = mapped_column(Integer)
    end_line: Mapped[int] = mapped_column(Integer)
    start_byte: Mapped[int] = mapped_column(BigInteger)
    end_byte: Mapped[int] = mapped_column(BigInteger)
    reference: Mapped[str | None] = mapped_column(Text)


class CodeChunkRecord(Base):
    __tablename__ = "code_chunks"
    __table_args__ = (Index("ix_code_chunks_ws_path", "workspace_id", "path"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    path: Mapped[str] = mapped_column(String(4096))
    language: Mapped[str] = mapped_column(String(16))
    header_path: Mapped[str] = mapped_column(String(1024))
    kind: Mapped[str] = mapped_column(String(16))
    start_line: Mapped[int] = mapped_column(Integer)
    end_line: Mapped[int] = mapped_column(Integer)
    start_byte: Mapped[int] = mapped_column(BigInteger)
    end_byte: Mapped[int] = mapped_column(BigInteger)
    # Set when index-time screening finds an injection-pattern payload (SEC-PI).
    is_suspect: Mapped[bool] = mapped_column(Boolean, default=False)


class CodeReferenceRecord(Base):
    """An unresolved reference captured at parse time (M5). Resolved into
    ``graph_edges`` by name at graph-build time; kept per-file so an incremental
    re-index replaces just the changed file's references."""

    __tablename__ = "code_references"
    __table_args__ = (Index("ix_code_references_ws_path", "workspace_id", "path"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    path: Mapped[str] = mapped_column(String(4096))
    kind: Mapped[str] = mapped_column(String(16))
    from_qualified_name: Mapped[str] = mapped_column(String(1024))
    target_name: Mapped[str] = mapped_column(String(512))
    line: Mapped[int] = mapped_column(Integer)


class GraphNodeRecord(Base):
    """A knowledge-graph node: a module or a symbol (ADR-0003). Unique within a
    workspace by ``(path, qualified_name)``."""

    __tablename__ = "graph_nodes"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id", "path", "qualified_name", name="uq_graph_nodes_ws_path_qn"
        ),
        Index("ix_graph_nodes_ws_name", "workspace_id", "name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    path: Mapped[str] = mapped_column(String(4096))
    qualified_name: Mapped[str] = mapped_column(String(1024))
    name: Mapped[str] = mapped_column(String(512))
    kind: Mapped[str] = mapped_column(String(16))
    start_line: Mapped[int] = mapped_column(Integer)


class GraphEdgeRecord(Base):
    """A directed edge between two nodes of the same workspace. ``workspace_id``
    is denormalized so traversal CTEs stay scoped with a single indexed column."""

    __tablename__ = "graph_edges"
    __table_args__ = (
        Index("ix_graph_edges_ws_src_kind", "workspace_id", "src_id", "kind"),
        Index("ix_graph_edges_ws_dst_kind", "workspace_id", "dst_id", "kind"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    src_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("graph_nodes.id", ondelete="CASCADE"))
    dst_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("graph_nodes.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(16))
    line: Mapped[int | None] = mapped_column(Integer)
