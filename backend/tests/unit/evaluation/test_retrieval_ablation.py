"""Retrieval v2 rerank ablation: the eval gate that adopts or rejects reranking."""

from __future__ import annotations

from typing import TYPE_CHECKING

from spidey.evaluation.application import AblationCase, AblationDoc, RetrievalAblationSuite
from spidey.evaluation.domain import Tier

if TYPE_CHECKING:
    from collections.abc import Sequence


class KeywordReranker:
    """Scores a document 1.0 when it contains ``keyword``, else 0.0."""

    def __init__(self, keyword: str) -> None:
        self._keyword = keyword

    def score(self, *, query: str, documents: Sequence[str]) -> list[float]:
        _ = query
        return [1.0 if self._keyword in doc else 0.0 for doc in documents]


def _case(order: tuple[str, ...], texts: dict[str, str], relevant: set[str]) -> AblationCase:
    return AblationCase(
        query="find the answer",
        documents=tuple(AblationDoc(id=i, text=texts[i]) for i in order),
        relevant=frozenset(relevant),
    )


class TestRetrievalAblationSuite:
    def test_empty_cases_pass_with_no_metrics(self) -> None:
        outcome = RetrievalAblationSuite(cases=[], reranker=KeywordReranker("x")).run()
        assert outcome.passed
        assert outcome.metrics == {}

    def test_reranking_that_improves_order_passes_with_positive_delta(self) -> None:
        # Baseline ranks the irrelevant doc first; the reranker lifts the relevant
        # one, so NDCG and MRR both improve.
        case = _case(
            ("d1", "d2"),
            {"d1": "noise about nothing", "d2": "the relevant answer"},
            {"d2"},
        )
        outcome = RetrievalAblationSuite(cases=[case], reranker=KeywordReranker("relevant")).run()
        assert outcome.passed
        assert outcome.metrics["ndcg_at_5_delta"] > 0
        assert outcome.metrics["mrr_delta"] > 0
        assert outcome.metrics["ndcg_at_5_reranked"] == 1.0

    def test_neutral_reranker_does_not_regress(self) -> None:
        case = _case(
            ("d1", "d2"),
            {"d1": "noise", "d2": "the relevant answer"},
            {"d2"},
        )
        # A reranker that scores nothing leaves first-stage order intact → neutral.
        outcome = RetrievalAblationSuite(cases=[case], reranker=KeywordReranker("absent")).run()
        assert outcome.passed
        assert outcome.metrics["ndcg_at_5_delta"] == 0.0

    def test_reranking_that_regresses_fails(self) -> None:
        # Baseline is already ideal; a reranker that prefers the irrelevant doc
        # regresses ranking quality and must fail the gate.
        case = _case(
            ("d2", "d1"),
            {"d2": "the relevant answer", "d1": "noise keyword"},
            {"d2"},
        )
        outcome = RetrievalAblationSuite(cases=[case], reranker=KeywordReranker("keyword")).run()
        assert not outcome.passed
        assert outcome.metrics["ndcg_at_5_delta"] < 0
        assert any("regressed" in failure for failure in outcome.failures)

    def test_default_tier_is_t2(self) -> None:
        suite = RetrievalAblationSuite(cases=[], reranker=KeywordReranker("x"))
        assert suite.tier is Tier.T2
        assert suite.name == "retrieval_rerank_ablation"
