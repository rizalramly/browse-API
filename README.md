# gen-api

Self-hosted Gen web-search API for internal RAG and AI agent systems, with a
**pluggable acquisition layer**:

| Provider              | Status               | Used for (default)                          |
|-----------------------|----------------------|---------------------------------------------|
| GenXNG (on-prem, SearXNG-based) | live       | search, images, news, videos, autocomplete  |
| Commercial search API | ready, needs key     | places, shopping, scholar, patents, KG/PAA  |
| Direct scrape         | documented stub      | experimental only, off by feature flag      |

Every provider call goes through a resilience wrapper: timeout, up to 2
retries with exponential backoff (transient failures only), and a
per-provider circuit breaker (opens after 5 consecutive failures, half-open
trial after 30 s) so a dead backend fails fast instead of hanging consumers.

## Quickstart

Windows (one command — creates `.env`, builds, starts, waits for health,
creates a first API key if none exists):

```bash
powershell -ExecutionPolicy Bypass -File .\run.ps1
```

`.\run.ps1 -Down` stops the stack (keeps data); `.\run.ps1 -Reset` also wipes
the data volumes (API keys, usage log).

Manual equivalent (any platform):

```bash
cp .env.example .env    # then edit SEARXNG_SECRET at minimum
docker compose up --build -d
curl http://localhost:8000/healthz
curl http://localhost:8000/health/deps
```

OpenAPI docs: <http://localhost:8000/docs>. SearXNG debug UI: <http://localhost:8081>.

## Endpoints (contract)

All endpoints are `POST` with a JSON body (`/search`, `/images`, `/news`,
`/places`, `/videos`, `/shopping`, `/scholar`, `/patents`, `/autocomplete`).
Common fields: `q` (required), `gl`, `hl`, `location`, `num`, `page`, `tbs`,
plus `debug` to include `providersUsed` provenance in the response.
Every response echoes `searchParameters` and returns `credits`.

Live now (SearXNG): `/search`, `/images`, `/news`, `/videos`, `/autocomplete`.
`/places`, `/shopping`, `/scholar`, `/patents` are served by the commercial
adapter: set `COMMERCIAL_BASE_URL` and `COMMERCIAL_API_KEY` (env or Vault) to
activate them; until then they return `501` with a clear message. Setting
`SEARCH_ENRICHMENT=true` additionally grafts commercial
`knowledgeGraph`/`peopleAlsoAsk` onto SearXNG-served `/search` responses
(best-effort — enrichment failures never fail the request).

Auth: send `X-API-KEY`. Create keys with
`docker compose exec api python -m app.cli create-key --name <consumer> [--credits N]`.

Quota and limits: each successful query deducts credits from the key's balance
(1 per query; 2 for places/scholar/patents) — `402` when the balance can't
cover the cost, and nothing is charged for failed requests. A per-key token
bucket (`RATE_LIMIT_QPS`/`RATE_LIMIT_BURST`) returns `429` with `Retry-After`.
Every served request is recorded in the Postgres `usage_log` table.

Governance: a classification gate ([policy/sensitive.yml](policy/sensitive.yml),
versioned seed deny-list — refine with governance review) runs before the
cache and every provider. Matching queries **fail closed**: HTTP 403 with
`policyBlocked: true`, no egress on any path, no cache write, no charge, and
only a hashed query in logs. Be precise about the model: for allowed queries
the query text *does* reach the upstream engines GenXNG scrapes — what this
service avoids versus a commercial SERP vendor is third-party SaaS account
retention, not egress. Truly sensitive queries must not hit any external
search, which is exactly what the gate enforces.

Result quality: GenXNG-served responses carry a `searchMeta` block
(engine coverage, result sufficiency, duplicate rate, weighted
`qualityScore`, `degraded` flag) so consumers can detect
plausible-but-degraded results instead of trusting HTTP 200. Weights and
threshold via `QUALITY_*` env vars.

Quality fall-through: when a GenXNG response is degraded and the commercial
provider is configured, the API retries via commercial and serves the better
result (`QUALITY_FALLTHROUGH`, on by default; fails soft). `providersUsed`
and the `gen_api_fallthrough_total{outcome}` metric report the truth about
who served — a rising fall-through rate means GenXNG is quietly failing.

Engine health: a background task probes every enabled engine
(`ENGINE_PROBE_INTERVAL`, 15 min default; each round is real outbound
traffic, so tune to your egress budget). An engine failing
`ENGINE_FAIL_THRESHOLD` consecutive probes is quarantined — live requests
select only healthy engines for its category — and auto-recovers on the
next good probe. `gen_api_healthy_engines{category}` exposes the count.

Observability: Prometheus metrics at `/metrics` — request counts by outcome,
provider success/error rates, latency histograms (p50/p95 via
`histogram_quantile`), cache hit rate, `qualityScore` distribution and
degraded-response counts, all labelled per vertical and provider. Logs are
structured JSON, one `request served` line per request; query text is never
logged (a 16-char hash correlates repeats; opt in with `LOG_QUERIES=true`).

## Development

```bash
python -m venv .venv
.venv/Scripts/activate          # Windows
pip install -e .[dev]
pytest
ruff check .
mypy
```

A step-by-step consumer guide (auth, all endpoints, error handling, credits,
rate limits) lives in [docs/API_USAGE.md](docs/API_USAGE.md). Operators:
[docs/RUNBOOK.md](docs/RUNBOOK.md) — dashboard questions with PromQL, alert
thresholds, block-spike response, weekly probe schedule, and the fallback
economics note.

## Using it from RAG code

```python
from examples.rag_client import GenSearchClient

client = GenSearchClient("http://localhost:8000", api_key="<your key>")
context = client.snippets("attention is all you need", num=5)
# ['Attention Is All You Need — The dominant sequence... (https://arxiv.org/abs/1706.03762)', ...]
```

[examples/rag_client.py](examples/rag_client.py) is dependency-light (httpx
only) and made to be copied into consumer codebases.

## Egress protection (single shared proxy)

Outbound calls to the metasearch backend are paced by a GCRA-style limiter
(`OUTBOUND_QPS`/`OUTBOUND_BURST`, jittered): consumer spikes queue and
smooth instead of bursting through the egress; a queue deeper than
`OUTBOUND_MAX_WAIT_SECONDS` fails fast with 502. Queue depth is visible as
`gen_api_outbound_wait_seconds`.

Two measurement scripts are made to run **on the app server, through the
corporate proxy** (they honor `HTTPS_PROXY` env vars):

```bash
python scripts/ceiling_probe.py --rates 0.2,0.5,1,2 --step-seconds 60
```
ramps real SERP-shaped request rates until the first block signature
(429/403, captcha/consent redirect, "unusual traffic") and reports the last
safe rate plus a suggested `OUTBOUND_QPS` (25% headroom). **It deliberately
provokes a block at the end — coordinate with ICT, run off-peak, re-run
weekly.**

```bash
python scripts/engine_probe.py --apply
```
checks every engine endpoint through the proxy and regenerates the
probe-managed `engines:` section of `searxng/settings.yml`, each entry
annotated `# passes proxy (checked YYYY-MM-DD)` or disabled with the
evidence — the engine set stays measured, not assumed.

## Load testing

```bash
python scripts/load_test.py --api-key <KEY> --requests 200 --concurrency 20
```

`--unique` bypasses the cache to exercise providers; the default repeated
query measures the cached path. Reports rps, status-code counts and
p50/p95/p99 latency. Note the default per-key rate limit (5 qps) will
dominate a load test unless raised via `RATE_LIMIT_QPS`.

## Project layout

```
app/
  main.py            FastAPI app + lifespan (Postgres pool, Redis client)
  config.py          all settings: provider routing, TTLs, credits, limits
  secrets.py         Vault KV-v2 loader, env-var fallback
  auth.py            X-API-KEY validation against Postgres
  cache.py           Redis response cache (per-vertical TTL)
  ratelimit.py       per-key token bucket (Redis Lua, atomic)
  db.py              api_keys + usage_log, atomic credit deduction
  metrics.py         Prometheus counters/histograms
  logging_config.py  JSON log formatter
  cli.py             `python -m app.cli create-key`
  schemas/           canonical Gen response models (one module per vertical)
  providers/         base ABC · searxng · commercial · direct_scrape (stub)
                     · resilience (retry + circuit breaker) · registry
  api/               health · metrics · verticals (shared request pipeline)
tests/               79 tests, recorded fixtures, no live network
scripts/             load_test.py
examples/            rag_client.py
```

## Configuration

All settings come from environment variables / `.env` (see `.env.example`),
parsed by [app/config.py](app/config.py). Secrets resolve through Vault when
`VAULT_ADDR`/`VAULT_TOKEN` are set, otherwise from env vars
([app/secrets.py](app/secrets.py)). Per-vertical provider routing, cache TTLs
and credit costs are overridable via `PROVIDER_MAP`, `CACHE_TTL`, `CREDIT_COST`
JSON env vars.
