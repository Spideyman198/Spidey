"""Retrieval-quality metrics (FR-2.3 eval).

Ranking metrics over a golden set: each case names a query and the identifiers
of the results that are actually relevant. The functions are pure and
order-sensitive — ``retrieved`` is a ranked list, best first — so they are
deterministic and unit-testable without any model or service.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from collections.abc import Collection, Sequence


class RetrievalCase(BaseModel):
    """One golden query and the identifiers of its relevant results."""

    model_config = ConfigDict(frozen=True)

    query: str
    relevant: frozenset[str] = Field(default_factory=frozenset)


def precision_at_k(retrieved: Sequence[str], relevant: Collection[str], k: int) -> float:
    """Fraction of the top-``k`` results that are relevant."""
    if k <= 0:
        return 0.0
    top = retrieved[:k]
    if not top:
        return 0.0
    hits = sum(1 for item in top if item in relevant)
    return hits / len(top)


def recall_at_k(retrieved: Sequence[str], relevant: Collection[str], k: int) -> float:
    """Fraction of all relevant results found within the top-``k``."""
    if not relevant:
        return 1.0  # nothing to find → vacuously complete
    found = sum(1 for item in retrieved[:k] if item in relevant)
    return found / len(relevant)


def reciprocal_rank(retrieved: Sequence[str], relevant: Collection[str]) -> float:
    """1/rank of the first relevant result, or 0 if none is retrieved."""
    for index, item in enumerate(retrieved, start=1):
        if item in relevant:
            return 1.0 / index
    return 0.0
