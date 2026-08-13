"""Prometheus metrics. Histograms give latency p50/p95 via histogram_quantile."""
from prometheus_client import Counter, Histogram

REQUESTS = Counter(
    "gen_api_requests_total",
    "API requests by vertical and outcome",
    ["vertical", "status"],
)

REQUEST_LATENCY = Histogram(
    "gen_api_request_latency_seconds",
    "End-to-end request latency",
    ["vertical"],
)

PROVIDER_REQUESTS = Counter(
    "gen_api_provider_requests_total",
    "Upstream provider calls by outcome",
    ["provider", "vertical", "outcome"],
)

PROVIDER_LATENCY = Histogram(
    "gen_api_provider_latency_seconds",
    "Upstream provider call latency",
    ["provider", "vertical"],
)

CACHE_REQUESTS = Counter(
    "gen_api_cache_requests_total",
    "Cache lookups by result",
    ["vertical", "result"],
)

PROVIDER_RETRIES = Counter(
    "gen_api_provider_retries_total",
    "Provider call retries after transient failures",
    ["provider"],
)
