"""Lightweight async load test for the API (M14, NFR-2 verification aid).

Drives concurrent requests at an endpoint for a fixed duration and reports
latency percentiles and throughput. Defaults to the unauthenticated readiness
probe so it is safe to point at any environment; pass --path to target another
route. This is an operator aid for the M14 load-test exit criterion, complementing
the in-cluster load test — not a CI gate.

Usage:
    python scripts/loadtest.py --base-url http://localhost:8000
    python scripts/loadtest.py --concurrency 50 --duration 30 --path /api/v1/health/live
"""

from __future__ import annotations

import argparse
import asyncio
import time

import httpx


async def _worker(
    client: httpx.AsyncClient, path: str, stop_at: float, latencies: list[float], errors: list[int]
) -> None:
    while time.monotonic() < stop_at:
        start = time.perf_counter()
        try:
            response = await client.get(path)
            latencies.append((time.perf_counter() - start) * 1000.0)
            if response.status_code >= 500:
                errors.append(response.status_code)
        except httpx.HTTPError:
            errors.append(0)


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, int(pct * len(ordered)))
    return round(ordered[idx], 2)


async def run(base_url: str, path: str, concurrency: int, duration: float) -> int:
    latencies: list[float] = []
    errors: list[int] = []
    stop_at = time.monotonic() + duration
    limits = httpx.Limits(max_connections=concurrency, max_keepalive_connections=concurrency)
    async with httpx.AsyncClient(base_url=base_url, timeout=10.0, limits=limits) as client:
        await asyncio.gather(
            *(_worker(client, path, stop_at, latencies, errors) for _ in range(concurrency))
        )

    total = len(latencies) + len(errors)
    rps = round(total / duration, 1)
    print(f"target:      {base_url}{path}")
    print(f"concurrency: {concurrency}   duration: {duration}s")
    print(f"requests:    {total}   throughput: {rps} req/s   errors: {len(errors)}")
    print(f"latency ms:  p50={_percentile(latencies, 0.50)}  "
          f"p95={_percentile(latencies, 0.95)}  p99={_percentile(latencies, 0.99)}")
    return 1 if errors else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--path", default="/api/v1/health/ready")
    parser.add_argument("--concurrency", type=int, default=20)
    parser.add_argument("--duration", type=float, default=15.0)
    args = parser.parse_args(argv)
    return asyncio.run(run(args.base_url, args.path, args.concurrency, args.duration))


if __name__ == "__main__":
    raise SystemExit(main())
