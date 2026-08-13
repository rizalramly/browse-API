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

Observability: Prometheus metrics at `/metrics` — request counts by outcome,
provider success/error rates, latency histograms (p50/p95 via
`histogram_quantile`), and cache hit rate, all labelled per vertical and
provider. Logs are structured JSON, one `request served` line per request.

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
rate limits) lives in [docs/API_USAGE.md](docs/API_USAGE.md).

## Using it from RAG code

```python
from examples.rag_client import GenSearchClient

client = GenSearchClient("http://localhost:8000", api_key="<your key>")
context = client.snippets("attention is all you need", num=5)
# ['Attention Is All You Need — The dominant sequence... (https://arxiv.org/abs/1706.03762)', ...]
```

[examples/rag_client.py](examples/rag_client.py) is dependency-light (httpx
only) and made to be copied into consumer codebases.

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
