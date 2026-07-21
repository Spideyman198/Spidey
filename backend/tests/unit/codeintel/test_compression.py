"""Pure context compression (domain.compression) — extractive, provenance-exact."""

from __future__ import annotations

from spidey.codeintel.domain.compression import CompressionPolicy, compress_hits
from spidey.codeintel.domain.models import Language, SearchHit, SymbolKind


def _hit(content: str, *, start_line: int = 10) -> SearchHit:
    return SearchHit(
        path="app.py",
        language=Language.PYTHON,
        header_path="mod.f",
        kind=SymbolKind.FUNCTION,
        start_line=start_line,
        end_line=start_line + content.count("\n"),
        content=content,
        score=0.9,
        suspect=False,
        source="hybrid",
    )


class TestCompressHits:
    def test_empty_returns_empty(self) -> None:
        assert compress_hits([], policy=CompressionPolicy(), query="q") == []

    def test_keeps_query_window_and_reanchors_lines(self) -> None:
        content = "\n".join(["line a", "line b", "target token here", "line d"])
        hit = _hit(content, start_line=10)  # "target token here" is absolute line 12
        policy = CompressionPolicy(char_budget=10_000, per_hit_max_chars=10_000, context_lines=0)
        out = compress_hits([hit], policy=policy, query="target")
        assert out[0].content == "target token here"
        assert out[0].start_line == 12
        assert out[0].end_line == 12

    def test_context_lines_expand_the_window(self) -> None:
        content = "\n".join(["a", "b", "target", "d", "e"])
        hit = _hit(content, start_line=1)
        policy = CompressionPolicy(char_budget=10_000, per_hit_max_chars=10_000, context_lines=1)
        out = compress_hits([hit], policy=policy, query="target")
        assert out[0].content == "b\ntarget\nd"
        assert out[0].start_line == 2
        assert out[0].end_line == 4

    def test_no_term_match_falls_back_to_head(self) -> None:
        content = "\n".join(["alpha", "beta", "gamma", "delta"])
        hit = _hit(content, start_line=5)
        policy = CompressionPolicy(char_budget=10_000, per_hit_max_chars=10_000, context_lines=0)
        out = compress_hits([hit], policy=policy, query="nonexistent")
        assert out[0].content == "alpha"
        assert out[0].start_line == 5

    def test_per_hit_cap_truncates_content(self) -> None:
        hit = _hit("x" * 500, start_line=1)
        policy = CompressionPolicy(char_budget=10_000, per_hit_max_chars=100, context_lines=8)
        out = compress_hits([hit], policy=policy, query="anything")
        assert len(out[0].content) == 100

    def test_budget_stops_further_hits_but_keeps_first(self) -> None:
        hits = [_hit(f"body {i}\nmore", start_line=1) for i in range(4)]
        policy = CompressionPolicy(char_budget=1, per_hit_max_chars=10_000, context_lines=8)
        out = compress_hits(hits, policy=policy, query="body")
        assert len(out) == 1  # first hit always kept even past budget

    def test_budget_admits_hits_until_exhausted(self) -> None:
        hits = [_hit("kw", start_line=1) for _ in range(5)]  # 2 chars each
        policy = CompressionPolicy(char_budget=5, per_hit_max_chars=10_000, context_lines=0)
        out = compress_hits(hits, policy=policy, query="kw")
        # first (2) + second (4) fit; third would reach 6 > 5 → stop at 2.
        assert len(out) == 2
