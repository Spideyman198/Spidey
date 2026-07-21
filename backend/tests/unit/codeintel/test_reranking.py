"""Pure reranking fusion (domain.reranking) — deterministic, model-free."""

from __future__ import annotations

import pytest

from spidey.codeintel.domain.models import Language, SearchHit, SymbolKind
from spidey.codeintel.domain.reranking import rerank_hits
from spidey.platform.errors import ValidationFailedError


def _hit(header: str, score: float, *, source: str = "hybrid") -> SearchHit:
    return SearchHit(
        path="app.py",
        language=Language.PYTHON,
        header_path=header,
        kind=SymbolKind.FUNCTION,
        start_line=1,
        end_line=2,
        content=f"def {header}(): ...",
        score=score,
        suspect=False,
        source=source,
    )


class TestRerankHits:
    def test_empty_pool_returns_empty(self) -> None:
        assert rerank_hits([], []) == []

    def test_length_mismatch_raises(self) -> None:
        with pytest.raises(ValidationFailedError):
            rerank_hits([_hit("a", 0.9)], [0.1, 0.2])

    def test_reranker_only_blend_orders_by_reranker_score(self) -> None:
        hits = [_hit("a", 0.9), _hit("b", 0.5), _hit("c", 0.1)]
        # First-stage order is a, b, c; reranker prefers c, then b, then a.
        out = rerank_hits(hits, [0.0, 0.5, 1.0], blend=1.0)
        assert [h.header_path for h in out] == ["c", "b", "a"]

    def test_first_stage_only_blend_preserves_base_order(self) -> None:
        hits = [_hit("a", 0.9), _hit("b", 0.5)]
        # blend 0 ignores the reranker entirely → base order stands.
        out = rerank_hits(hits, [0.0, 1.0], blend=0.0)
        assert [h.header_path for h in out] == ["a", "b"]

    def test_ties_are_stable(self) -> None:
        hits = [_hit("a", 0.5), _hit("b", 0.5)]
        out = rerank_hits(hits, [0.5, 0.5], blend=0.7)
        assert [h.header_path for h in out] == ["a", "b"]

    def test_source_is_preserved_for_symbol_promotion(self) -> None:
        hits = [_hit("a", 0.9, source="hybrid"), _hit("b", 0.5, source="symbol")]
        out = rerank_hits(hits, [1.0, 0.0], blend=1.0)
        by_header = {h.header_path: h.source for h in out}
        assert by_header == {"a": "hybrid", "b": "symbol"}

    def test_fused_score_is_written_and_bounded(self) -> None:
        hits = [_hit("a", 0.9), _hit("b", 0.1)]
        out = rerank_hits(hits, [1.0, 0.0], blend=0.5)
        assert out[0].score == pytest.approx(1.0)
        assert all(0.0 <= h.score <= 1.0 for h in out)

    def test_blend_is_clamped(self) -> None:
        hits = [_hit("a", 0.9), _hit("b", 0.5)]
        # Out-of-range blend is clamped, not an error; 5.0 behaves like 1.0.
        out = rerank_hits(hits, [0.0, 1.0], blend=5.0)
        assert [h.header_path for h in out] == ["b", "a"]
