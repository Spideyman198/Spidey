"""Profile the retrieval v2 hot paths (M13, NFR-2).

Microbenchmarks the CPU-bound stages M13 adds to the search path — rerank score
fusion, context compression, and provenance framing — plus the NDCG metric, over
a synthetic candidate pool. It reports p50/p95/p99 per stage so a regression in
the pure ranking/compression code is visible without a live index.

What this does NOT measure: cross-encoder model inference (model/hardware-bound,
graded on the live nightly tier) and the Qdrant hybrid query (network + index
size). Those are the other terms in the NFR-2 search budget; see
docs/perf/m13-retrieval-perf.md for how the full budget is decomposed.

Usage:
    python scripts/profile_retrieval.py                       # print a table
    python scripts/profile_retrieval.py --pool 60 --iters 2000
    python scripts/profile_retrieval.py --json out/perf.json  # also write JSON
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Callable
from pathlib import Path

from spidey.codeintel.domain import CompressionPolicy, compress_hits, frame_hits, rerank_hits
from spidey.codeintel.domain.models import Language, SearchHit, SymbolKind
from spidey.evaluation.domain import ndcg_at_k
from spidey.llm.infrastructure import LexicalOverlapReranker

_QUERY = "parse config loader validate settings"


def _synthetic_hit(index: int) -> SearchHit:
    lines = [f"def handler_{index}(request):"]
    lines += [f"    step_{j} = compute(request, {j})" for j in range(38)]
    lines.append("    return validate(settings, step_0)")
    return SearchHit(
        path=f"module_{index}.py",
        language=Language.PYTHON,
        header_path=f"module_{index}.handler_{index}",
        kind=SymbolKind.FUNCTION,
        start_line=1,
        end_line=len(lines),
        content="\n".join(lines),
        score=1.0 - index / 1000.0,
        suspect=False,
        source="hybrid",
    )


def _percentiles(samples_us: list[float]) -> dict[str, float]:
    ordered = sorted(samples_us)
    n = len(ordered)

    def at(p: float) -> float:
        idx = min(n - 1, int(p * n))
        return round(ordered[idx], 2)

    return {
        "p50_us": at(0.50),
        "p95_us": at(0.95),
        "p99_us": at(0.99),
        "mean_us": round(sum(ordered) / n, 2),
    }


def _time(label: str, fn: Callable[[], object], iters: int) -> tuple[str, dict[str, float]]:
    fn()  # warm up (import-time caches, first-call allocation)
    samples: list[float] = []
    for _ in range(iters):
        start = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - start) * 1_000_000.0)
    return label, _percentiles(samples)


def run(pool_size: int, iters: int) -> dict[str, dict[str, float]]:
    hits = [_synthetic_hit(i) for i in range(pool_size)]
    reranker = LexicalOverlapReranker()
    policy = CompressionPolicy()
    relevant = {hits[0].header_path, hits[3].header_path, hits[7].header_path}

    def rerank_stage() -> object:
        scores = reranker.score(query=_QUERY, documents=[h.content for h in hits])
        return rerank_hits(hits, scores, blend=0.7)

    def compress_stage() -> object:
        return compress_hits(hits[:10], policy=policy, query=_QUERY)

    def frame_stage() -> object:
        return frame_hits(hits[:10])

    def ndcg_stage() -> object:
        return ndcg_at_k([h.header_path for h in hits], relevant, 5)

    stages = [
        _time("rerank_fusion", rerank_stage, iters),
        _time("context_compression", compress_stage, iters),
        _time("provenance_framing", frame_stage, iters),
        _time("ndcg_at_5", ndcg_stage, iters),
    ]
    return dict(stages)


def _print_table(pool_size: int, iters: int, results: dict[str, dict[str, float]]) -> None:
    print(f"retrieval v2 hot-path profile - pool={pool_size} candidates, iters={iters}\n")
    header = f"{'stage':<22} {'p50 (us)':>10} {'p95 (us)':>10} {'p99 (us)':>10} {'mean (us)':>10}"
    print(header)
    print("-" * len(header))
    for stage, stats in results.items():
        print(
            f"{stage:<22} {stats['p50_us']:>10} {stats['p95_us']:>10} "
            f"{stats['p99_us']:>10} {stats['mean_us']:>10}"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pool", type=int, default=60, help="candidate pool size to rerank")
    parser.add_argument("--iters", type=int, default=2000, help="timed iterations per stage")
    parser.add_argument("--json", type=Path, default=None, help="also write results as JSON")
    args = parser.parse_args(argv)

    results = run(args.pool, args.iters)
    _print_table(args.pool, args.iters, results)

    if args.json is not None:
        payload = {"pool_size": args.pool, "iters": args.iters, "stages": results}
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"\nwrote {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
