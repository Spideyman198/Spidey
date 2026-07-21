"""Retrieval eval suite: grades a retriever against a golden query set.

The suite is deliberately transport-agnostic — it drives a plain
``retriever(query, k) -> ranked ids`` callable, so the same suite grades the
live hybrid search (integration/nightly) or a cached golden ranking. It reports
mean precision@k, recall@k, and MRR; a query that surfaces no relevant result
in its top-k is a hard miss recorded in ``failures``. Metric floors are enforced
separately by the blessed baselines (evaluation/baselines/retrieval.json).
"""

from __future__ import annotations

from statistics import fmean
from typing import TYPE_CHECKING

from spidey.evaluation.domain import SuiteOutcome, Tier
from spidey.evaluation.domain.retrieval import (
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
    reciprocal_rank,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from spidey.evaluation.domain.retrieval import RetrievalCase


class RetrievalEvalSuite:
    """Grades a retriever over golden cases; satisfies the ``EvalSuite`` port."""

    def __init__(
        self,
        *,
        cases: Sequence[RetrievalCase],
        retriever: Callable[[str, int], Sequence[str]],
        name: str = "retrieval",
        tier: Tier = Tier.T2,
        k: int = 5,
    ) -> None:
        self._cases = list(cases)
        self._retriever = retriever
        self._name = name
        self._tier = tier
        self._k = k

    @property
    def name(self) -> str:
        return self._name

    @property
    def tier(self) -> Tier:
        return self._tier

    def run(self) -> SuiteOutcome:
        if not self._cases:
            return SuiteOutcome(passed=True, metrics={}, failures=[])

        precisions: list[float] = []
        recalls: list[float] = []
        rrs: list[float] = []
        ndcgs: list[float] = []
        failures: list[str] = []

        for case in self._cases:
            retrieved = list(self._retriever(case.query, self._k))
            precisions.append(precision_at_k(retrieved, case.relevant, self._k))
            recalls.append(recall_at_k(retrieved, case.relevant, self._k))
            ndcgs.append(ndcg_at_k(retrieved, case.relevant, self._k))
            rr = reciprocal_rank(retrieved, case.relevant)
            rrs.append(rr)
            if rr == 0.0:
                failures.append(f"no relevant result in top-{self._k} for {case.query!r}")

        metrics = {
            f"precision_at_{self._k}": round(fmean(precisions), 4),
            f"recall_at_{self._k}": round(fmean(recalls), 4),
            f"ndcg_at_{self._k}": round(fmean(ndcgs), 4),
            "mrr": round(fmean(rrs), 4),
            "hit_rate": round(1.0 - len(failures) / len(self._cases), 4),
        }
        return SuiteOutcome(passed=not failures, metrics=metrics, failures=failures)
