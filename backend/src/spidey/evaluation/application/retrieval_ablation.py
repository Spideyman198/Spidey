"""Retrieval v2 ablation (M13, FR-2.7): does reranking earn its place?

The M13 reranker and compression features are *eval-gated* — they land only if
they measurably improve retrieval on a golden set. This suite is that gate for
reranking. Each case supplies a candidate pool already in first-stage (dense +
sparse RRF) order; the suite scores that baseline order, reranks the pool with
the injected reranker and the same convex fusion the live search uses, scores
the reranked order, and reports before/after/delta on NDCG@k and MRR.

It PASSES when reranking is at least neutral (does not regress NDCG@k or MRR) —
so the ablation is a genuine adopt/reject decision, not a rubber stamp. The
suite is deterministic and model-free when driven by the lexical reranker, so it
runs in CI; the ONNX cross-encoder is graded the same way on the live tier.

Kept self-contained — it depends only on ``evaluation.domain`` metrics, never on
``codeintel`` — so bounded-context independence holds (import-linter).
"""

from __future__ import annotations

from statistics import fmean
from typing import TYPE_CHECKING, Protocol

from pydantic import BaseModel, ConfigDict, Field

from spidey.evaluation.domain import SuiteOutcome, Tier
from spidey.evaluation.domain.retrieval import ndcg_at_k, reciprocal_rank

if TYPE_CHECKING:
    from collections.abc import Sequence


class Reranker(Protocol):
    """Structural port for a reranker — matches codeintel's without importing it."""

    def score(self, *, query: str, documents: Sequence[str]) -> list[float]: ...


class AblationDoc(BaseModel):
    """One candidate in a pool: an identity and the text a reranker sees."""

    model_config = ConfigDict(frozen=True)

    id: str
    text: str


class AblationCase(BaseModel):
    """A query, its first-stage-ordered candidate pool, and the relevant ids."""

    model_config = ConfigDict(frozen=True)

    query: str
    documents: tuple[AblationDoc, ...]
    relevant: frozenset[str] = Field(default_factory=frozenset)


def _min_max(values: Sequence[float]) -> list[float]:
    if not values:
        return []
    lo, hi = min(values), max(values)
    span = hi - lo
    if span <= 0.0:
        return [0.5] * len(values)
    return [(v - lo) / span for v in values]


def _fused_order(
    docs: Sequence[AblationDoc], rerank_scores: Sequence[float], *, blend: float
) -> list[str]:
    """Reorder ids by blending first-stage rank with reranker score.

    First-stage scores are synthesized from pool position (``1/rank``) — the pool
    is already in first-stage order — then min-max normalized and blended with the
    normalized reranker scores, matching the live search's fusion policy.
    """
    base = [1.0 / (rank + 1) for rank in range(len(docs))]
    base_n = _min_max(base)
    rerank_n = _min_max(list(rerank_scores))
    fused = [blend * rerank_n[i] + (1.0 - blend) * base_n[i] for i in range(len(docs))]
    order = sorted(range(len(docs)), key=lambda i: (-fused[i], i))
    return [docs[i].id for i in order]


class RetrievalAblationSuite:
    """Grades reranked vs first-stage ordering; satisfies the ``EvalSuite`` port."""

    def __init__(
        self,
        *,
        cases: Sequence[AblationCase],
        reranker: Reranker,
        blend: float = 0.7,
        k: int = 5,
        name: str = "retrieval_rerank_ablation",
        tier: Tier = Tier.T2,
    ) -> None:
        self._cases = list(cases)
        self._reranker = reranker
        self._blend = blend
        self._k = k
        self._name = name
        self._tier = tier

    @property
    def name(self) -> str:
        return self._name

    @property
    def tier(self) -> Tier:
        return self._tier

    def run(self) -> SuiteOutcome:
        if not self._cases:
            return SuiteOutcome(passed=True, metrics={}, failures=[])

        base_ndcg: list[float] = []
        rerank_ndcg: list[float] = []
        base_mrr: list[float] = []
        rerank_mrr: list[float] = []
        failures: list[str] = []

        for case in self._cases:
            baseline = [doc.id for doc in case.documents]
            scores = self._reranker.score(
                query=case.query, documents=[doc.text for doc in case.documents]
            )
            reranked = _fused_order(case.documents, scores, blend=self._blend)

            base_ndcg.append(ndcg_at_k(baseline, case.relevant, self._k))
            rerank_ndcg.append(ndcg_at_k(reranked, case.relevant, self._k))
            base_mrr.append(reciprocal_rank(baseline, case.relevant))
            rerank_mrr.append(reciprocal_rank(reranked, case.relevant))

        ndcg_before, ndcg_after = fmean(base_ndcg), fmean(rerank_ndcg)
        mrr_before, mrr_after = fmean(base_mrr), fmean(rerank_mrr)
        ndcg_delta = ndcg_after - ndcg_before
        mrr_delta = mrr_after - mrr_before

        # Adopt criterion: reranking must not regress ranking quality. A tiny
        # epsilon absorbs float noise so a genuine tie is not read as a loss.
        eps = 1e-9
        if ndcg_delta < -eps:
            failures.append(f"reranking regressed ndcg_at_{self._k} by {-ndcg_delta:.4f}")
        if mrr_delta < -eps:
            failures.append(f"reranking regressed mrr by {-mrr_delta:.4f}")

        metrics = {
            f"ndcg_at_{self._k}_baseline": round(ndcg_before, 4),
            f"ndcg_at_{self._k}_reranked": round(ndcg_after, 4),
            f"ndcg_at_{self._k}_delta": round(ndcg_delta, 4),
            "mrr_baseline": round(mrr_before, 4),
            "mrr_reranked": round(mrr_after, 4),
            "mrr_delta": round(mrr_delta, 4),
        }
        return SuiteOutcome(passed=not failures, metrics=metrics, failures=failures)
