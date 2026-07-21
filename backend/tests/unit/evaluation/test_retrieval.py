"""Retrieval metrics and the grading suite — pure, deterministic (T1)."""

from __future__ import annotations

from spidey.evaluation.application import RetrievalEvalSuite
from spidey.evaluation.domain import (
    RetrievalCase,
    Tier,
    dcg_at_k,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
    reciprocal_rank,
)


class TestMetrics:
    def test_precision_at_k_counts_hits_in_top_k(self) -> None:
        retrieved = ["a", "x", "b", "y", "z"]
        assert precision_at_k(retrieved, {"a", "b", "c"}, 4) == 0.5

    def test_precision_of_empty_is_zero(self) -> None:
        assert precision_at_k([], {"a"}, 5) == 0.0
        assert precision_at_k(["a"], {"a"}, 0) == 0.0

    def test_recall_at_k_is_fraction_of_relevant_found(self) -> None:
        retrieved = ["a", "b", "x"]
        assert recall_at_k(retrieved, {"a", "b", "c", "d"}, 3) == 0.5

    def test_recall_with_no_relevant_is_vacuously_full(self) -> None:
        assert recall_at_k(["a"], set(), 3) == 1.0

    def test_reciprocal_rank_uses_first_relevant_position(self) -> None:
        assert reciprocal_rank(["x", "y", "a"], {"a"}) == 1 / 3
        assert reciprocal_rank(["a", "y"], {"a"}) == 1.0

    def test_reciprocal_rank_zero_when_absent(self) -> None:
        assert reciprocal_rank(["x", "y"], {"a"}) == 0.0

    def test_ndcg_is_one_for_ideal_order(self) -> None:
        assert ndcg_at_k(["a", "b", "x"], {"a", "b"}, 3) == 1.0

    def test_ndcg_rewards_higher_ranked_relevant_hits(self) -> None:
        # Same relevant set, better position → strictly higher NDCG. This is the
        # signal reranking moves that precision@k (position-blind) does not.
        good = ndcg_at_k(["a", "x", "y"], {"a"}, 3)
        worse = ndcg_at_k(["x", "y", "a"], {"a"}, 3)
        assert good == 1.0
        assert worse < good

    def test_ndcg_no_relevant_is_vacuously_ideal(self) -> None:
        assert ndcg_at_k(["x", "y"], set(), 3) == 1.0

    def test_dcg_discounts_by_log_rank(self) -> None:
        # One relevant at rank 2 → 1/log2(3).
        from math import log2

        assert dcg_at_k(["x", "a"], {"a"}, 5) == 1.0 / log2(3)


def _retriever(table: dict[str, list[str]]):
    def retrieve(query: str, k: int) -> list[str]:
        return table[query][:k]

    return retrieve


class TestRetrievalSuite:
    def test_empty_cases_pass_with_no_metrics(self) -> None:
        suite = RetrievalEvalSuite(cases=[], retriever=_retriever({}))
        outcome = suite.run()
        assert outcome.passed
        assert outcome.metrics == {}

    def test_perfect_retrieval_scores_top_marks(self) -> None:
        cases = [
            RetrievalCase(query="q1", relevant=frozenset({"a"})),
            RetrievalCase(query="q2", relevant=frozenset({"b"})),
        ]
        table = {"q1": ["a", "x", "y"], "q2": ["b", "z"]}
        outcome = RetrievalEvalSuite(cases=cases, retriever=_retriever(table), k=3).run()
        assert outcome.passed
        assert outcome.metrics["mrr"] == 1.0
        assert outcome.metrics["hit_rate"] == 1.0

    def test_hard_miss_is_recorded_and_fails(self) -> None:
        cases = [
            RetrievalCase(query="hit", relevant=frozenset({"a"})),
            RetrievalCase(query="miss", relevant=frozenset({"b"})),
        ]
        table = {"hit": ["a"], "miss": ["x", "y", "z"]}
        outcome = RetrievalEvalSuite(cases=cases, retriever=_retriever(table), k=3).run()
        assert not outcome.passed
        assert outcome.metrics["hit_rate"] == 0.5
        assert any("miss" in failure for failure in outcome.failures)

    def test_default_tier_is_t2(self) -> None:
        # It drives live search (embeddings + Qdrant), so it is not a T1 smoke.
        suite = RetrievalEvalSuite(cases=[], retriever=_retriever({}))
        assert suite.tier is Tier.T2
        assert suite.name == "retrieval"
