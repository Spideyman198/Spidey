"""Embedding value types — shared kernel.

These are provider- and context-neutral math value objects. They live in the
shared kernel so both the ``llm`` context (which produces them) and consuming
contexts such as ``codeintel`` (which pass them to a vector store) can reference
the same types without importing each other — bounded-context independence.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

# A dense embedding is a fixed-width float vector.
DenseVector = list[float]


class SparseVector(BaseModel):
    """A sparse embedding: parallel index/value arrays (BM25 term weights).

    Server-side IDF is applied by the vector store, so values here are raw term
    frequencies/weights, not final scores.
    """

    model_config = ConfigDict(frozen=True)

    indices: list[int]
    values: list[float]
