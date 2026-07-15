"""Embedding value types — provider-neutral.

Re-exported from the shared kernel (:mod:`spidey.platform.vectors`) so both the
``llm`` and ``codeintel`` contexts reference identical types without importing
each other.
"""

from __future__ import annotations

from spidey.platform.vectors import DenseVector, SparseVector

__all__ = ["DenseVector", "SparseVector"]
