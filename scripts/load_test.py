"""Load test for gen-api.

Usage:
    python scripts/load_test.py --api-key <KEY> --requests 200 --concurrency 20
    python scripts/load_test.py --api-key <KEY> --vertical images --q "solar panel"

Repeated identical queries exercise the cache path; pass --unique to append a
counter to each query and force provider traffic instead.
"""
import argparse
import asyncio
import time

import httpx


async def worker(
    client: httpx.AsyncClient,
    path: str,
    body: dict[str, object],
    unique: bool,
    count: int,
    worker_id: int,
    results: list[tuple[int, float]],
) -> None:
    for i in range(count):
        payload = dict(body)
        if unique:
            payload["q"] = f"{body['q']} {worker_id}-{i}"
        start = time.perf_counter()
        try:
            response = await client.post(path, json=payload)
            results.append((response.status_code, time.perf_counter() - start))
        except httpx.HTTPError:
            results.append((0, time.perf_counter() - start))


def percentile(sorted_values: list[float], pct: float) -> float:
    if not sorted_values:
        return 0.0
    index = min(len(sorted_values) - 1, int(len(sorted_values) * pct / 100))
    return sorted_values[index]


async def run(args: argparse.Namespace) -> None:
    per_worker = max(1, args.requests // args.concurrency)
    total = per_worker * args.concurrency
    results: list[tuple[int, float]] = []
    body = {"q": args.q, "num": args.num}

    started = time.perf_counter()
    async with httpx.AsyncClient(
        base_url=args.url, headers={"X-API-KEY": args.api_key}, timeout=args.timeout
    ) as client:
        await asyncio.gather(
            *[
                worker(client, f"/{args.vertical}", body, args.unique, per_worker, w, results)
                for w in range(args.concurrency)
            ]
        )
    duration = time.perf_counter() - started

    codes: dict[int, int] = {}
    for code, _ in results:
        codes[code] = codes.get(code, 0) + 1
    ok_latencies = sorted(latency for code, latency in results if code == 200)

    print(f"requests:     {total} in {duration:.2f}s  ({total / duration:.1f} rps)")
    print(f"status codes: {dict(sorted(codes.items()))}")
    if ok_latencies:
        print(
            "latency (200s only):"
            f"  p50={percentile(ok_latencies, 50) * 1000:.0f}ms"
            f"  p95={percentile(ok_latencies, 95) * 1000:.0f}ms"
            f"  p99={percentile(ok_latencies, 99) * 1000:.0f}ms"
            f"  max={ok_latencies[-1] * 1000:.0f}ms"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="gen-api load test")
    parser.add_argument("--url", default="http://localhost:8000")
    parser.add_argument("--api-key", required=True)
    parser.add_argument("--vertical", default="search")
    parser.add_argument("--q", default="attention is all you need")
    parser.add_argument("--num", type=int, default=10)
    parser.add_argument("--requests", type=int, default=100)
    parser.add_argument("--concurrency", type=int, default=10)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--unique", action="store_true",
                        help="make every query unique (bypasses the cache)")
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
