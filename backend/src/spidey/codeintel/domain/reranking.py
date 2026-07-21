"""Reranking fusion (M13, FR-2.7) — pure, deterministic, model-free.

The first retrieval stage (dense + sparse RRF) is recall-oriented: it casts a
wide net cheaply. A cross-encoder reranker is precision-oriented but expensive,
so it runs only over the small candidate pool the first stage returns. This
module fuses the two signals — it does not call any model. Given the candidate
hits and the aligned reranker scores, it produces a re-ordered list whose
``score`` is a convex blend of the (min-max normalized) first-stage score and
the (min-max normalized) reranker score.

Keeping the fusion pure makes the ranking behaviour unit-testable without a
model and independent of the reranker adapter: the adapter's only job is to emit
one score per document; the ordering policy lives here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from spidey.platform.errors import ValidationFailedError

if TYPE_CHECKING:
    from collections.abc import Sequence

    from spidey.codeintel.domain.models import SearchHit


def _min_max_normalize(values: Sequence[float]) -> list[float]:
    """Scale ``values`` to [0, 1]; a flat vector maps to all-0.5 (no signal)."""
    if not values:
        return []
    lo = min(values)
    hi = max(values)
    span = hi - lo
    if span <= 0.0:
        return [0.5] * len(values)
    return [(v - lo) / span for v in values]


def rerank_hits(
    hits: Sequence[SearchHit],
    rerank_scores: Sequence[float],
    *,
    blend: float = 0.7,
) -> list[SearchHit]:
    """Reorder ``hits`` by a blend of first-stage and reranker scores.

    ``blend`` weights the reranker (1.0 = reranker only, 0.0 = first-stage only).
    The returned hits are copies whose ``score`` is the fused value in [0, 1];
    ``source`` is preserved so a later symbol-promotion pass still sees which hits
    were exact-symbol matches. The sort is stable, so ties keep candidate order.
    """
    if len(hits) != len(rerank_scores):
        msg = "rerank produced a score count that does not match the candidate pool"
        raise ValidationFailedError(msg, hits=len(hits), scores=len(rerank_scores))
    if not hits:
        return []

    clamped = min(max(blend, 0.0), 1.0)
    base_norm = _min_max_normalize([h.score for h in hits])
    rerank_norm = _min_max_normalize(list(rerank_scores))

    scored: list[tuple[float, int, SearchHit]] = []
    for index, hit in enumerate(hits):
        fused = clamped * rerank_norm[index] + (1.0 - clamped) * base_norm[index]
        scored.append((fused, index, hit))

    # Sort by fused score desc; the original index is a stable tie-break so equal
    # scores keep first-stage order (Python sort is stable, but the explicit key
    # makes the intent — and reversibility — unambiguous).
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [hit.model_copy(update={"score": round(fused, 6)}) for fused, _, hit in scored]
