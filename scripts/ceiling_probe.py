"""Measure the real block ceiling of THIS egress (improvement plan 1.1).

Run this ON the application server, through the corporate proxy (httpx honors
HTTP_PROXY/HTTPS_PROXY). It issues real SERP-shaped requests at rising rates,
step by step, until the first block signature (429/403, /sorry or captcha
redirect, "unusual traffic" interstitial), then reports the last safe rate
and a suggested OUTBOUND_QPS with headroom.

!! This deliberately provokes a block at its final step, on the SHARED
!! corporate egress IP. Coordinate with ICT before running, run it off-peak,
!! and re-run weekly — the ceiling drifts.

Usage:
    python scripts/ceiling_probe.py --rates 0.2,0.5,1,2 --step-seconds 60
    python scripts/ceiling_probe.py --out ceiling_report.json
"""
import argparse
import asyncio
import json
import time
from dataclasses import asdict, dataclass

import httpx

QUERIES = [
    "renewable energy trends", "python asyncio tutorial", "kuala lumpur weather",
    "electric vehicle charging", "machine learning basics", "world cup schedule",
    "solar panel efficiency", "grid battery storage economics",
]

BLOCK_BODY_MARKERS = ("unusual traffic", "captcha", "not a robot", "automated queries")
BLOCK_URL_MARKERS = ("/sorry", "captcha", "consent.google")


def classify_response(status: int, final_url: str, body_snippet: str) -> str:
    """'ok' | 'block' | 'error' — pure and unit-testable."""
    if status in (403, 429):
        return "block"
    lowered_url = final_url.lower()
    if any(marker in lowered_url for marker in BLOCK_URL_MARKERS):
        return "block"
    lowered_body = body_snippet.lower()
    if any(marker in lowered_body for marker in BLOCK_BODY_MARKERS):
        return "block"
    return "ok" if 200 <= status < 400 else "error"


def suggest_outbound_qps(last_safe_rate: float, headroom: float = 0.25) -> float:
    """Cap outbound at a fraction of the measured ceiling."""
    return round(last_safe_rate * headroom, 3)


@dataclass
class StepResult:
    rate: float
    sent: int
    ok: int
    blocks: int
    errors: int


async def run_step(
    client: httpx.AsyncClient, url_template: str, rate: float, seconds: float
) -> StepResult:
    result = StepResult(rate=rate, sent=0, ok=0, blocks=0, errors=0)
    interval = 1.0 / rate
    deadline = time.monotonic() + seconds
    query_index = 0
    while time.monotonic() < deadline:
        started = time.monotonic()
        query = QUERIES[query_index % len(QUERIES)]
        query_index += 1
        result.sent += 1
        try:
            response = await client.get(url_template.format(q=query.replace(" ", "+")))
            verdict = classify_response(
                response.status_code, str(response.url), response.text[:2000]
            )
        except httpx.HTTPError:
            verdict = "error"
        if verdict == "ok":
            result.ok += 1
        elif verdict == "block":
            result.blocks += 1
            return result  # first block ends the step (and the run)
        else:
            result.errors += 1
        elapsed = time.monotonic() - started
        if elapsed < interval:
            await asyncio.sleep(interval - elapsed)
    return result


async def run(args: argparse.Namespace) -> None:
    rates = [float(r) for r in args.rates.split(",")]
    steps: list[StepResult] = []
    last_safe: float | None = None

    async with httpx.AsyncClient(
        timeout=args.timeout,
        follow_redirects=True,
        headers={"User-Agent": args.user_agent},
        trust_env=True,  # honor corporate proxy env vars
    ) as client:
        for rate in rates:
            print(f"step: {rate} req/s for {args.step_seconds}s ...")
            step = await run_step(client, args.url, rate, args.step_seconds)
            steps.append(step)
            print(f"  sent={step.sent} ok={step.ok} blocks={step.blocks} errors={step.errors}")
            if step.blocks > 0:
                print(f"  BLOCKED at {rate} req/s — stopping ramp")
                break
            last_safe = rate
            await asyncio.sleep(args.cooldown_seconds)

    report = {
        "measured_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "url_template": args.url,
        "steps": [asdict(s) for s in steps],
        "last_safe_rate_qps": last_safe,
        "suggested_outbound_qps": suggest_outbound_qps(last_safe) if last_safe else None,
        "note": "re-run weekly; the ceiling drifts with shared-egress load",
    }
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2)
    print(f"\nreport written to {args.out}")
    if last_safe is not None:
        print(f"last safe rate: {last_safe} req/s "
              f"-> suggested OUTBOUND_QPS={suggest_outbound_qps(last_safe)}")
    else:
        print("blocked at the lowest tested rate — egress is already hot; "
              "retest off-peak or lower the starting rate")


def main() -> None:
    parser = argparse.ArgumentParser(description="egress block-ceiling probe")
    parser.add_argument("--url", default="https://www.google.com/search?q={q}&hl=en")
    parser.add_argument("--rates", default="0.2,0.5,1,2",
                        help="comma-separated req/s ramp, lowest first")
    parser.add_argument("--step-seconds", type=float, default=60)
    parser.add_argument("--cooldown-seconds", type=float, default=30)
    parser.add_argument("--timeout", type=float, default=15)
    parser.add_argument("--user-agent", default=(
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"))
    parser.add_argument("--out", default="ceiling_report.json")
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
