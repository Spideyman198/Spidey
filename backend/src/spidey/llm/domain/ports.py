"""Embedding ports.

These describe *what* the platform needs from an embedding provider. The M4
implementation is local (fastembed); a network provider would slot in behind
the same ports with the retry/budget middleware the M6 gateway adds — callers
never change.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Sequence

    from spidey.llm.domain.models import DenseVector, SparseVector


class DenseEmbedder(Protocol):
    @property
    def dimension(self) -> int: ...

    def embed_documents(self, texts: Sequence[str]) -> list[DenseVector]:
        """Embed a batch of documents. Order is preserved."""
        ...

    def embed_query(self, text: str) -> DenseVector: ...


class SparseEmbedder(Protocol):
    def embed_documents(self, texts: Sequence[str]) -> list[SparseVector]: ...

    def embed_query(self, text: str) -> SparseVector: ...
