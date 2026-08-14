"""Prometheus metrics. Histograms give latency p50/p95 via histogram_quantile."""
from prometheus_client import Counter, Gauge, Histogram

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

QUALITY_SCORE = Histogram(
    "gen_api_quality_score",
    "searchMeta.qualityScore distribution for provider-served responses",
    ["vertical"],
    buckets=[0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0],
)

DEGRADED_RESPONSES = Counter(
    "gen_api_degraded_responses_total",
    "Responses served with searchMeta.degraded=true",
    ["vertical"],
)

POLICY_BLOCKED = Counter(
    "gen_api_policy_blocked_total",
    "Queries refused by the egress classification gate",
    ["category"],
)

FALLTHROUGH = Counter(
    "gen_api_fallthrough_total",
    "Degraded genxng responses handed to the commercial provider",
    ["vertical", "outcome"],
)

HEALTHY_ENGINES = Gauge(
    "gen_api_healthy_engines",
    "Engines currently passing health probes, per category",
    ["category"],
)

ENGINE_PROBES = Counter(
    "gen_api_engine_probes_total",
    "Engine health probe outcomes",
    ["engine", "outcome"],
)

OUTBOUND_WAIT = Histogram(
    "gen_api_outbound_wait_seconds",
    "Seconds outbound genxng calls waited in the pacing queue",
    buckets=[0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 20.0],
)
