# gen-api Runbook

Operating guide for the self-hosted search API sitting first in the
web-search provider chain, behind a single corporate (Zscaler) egress.

**Owner:** _____________________ (named person; ~2h/month)
**Monthly check:** review the four dashboard questions below, re-run the
weekly probes if they've lapsed, skim `usage_log` for anomalies.

---

## The four dashboard questions

All from Prometheus at `http://<host>:8000/metrics`.

**1. Is gen-api actually carrying the traffic, or is the paid provider?**
The single most important number. If fall-through climbs, gen-api is quietly
failing and the paid bill is quietly rising.

```promql
# fall-through rate (share of GenXNG-degraded responses served commercially)
sum(rate(gen_api_fallthrough_total{outcome="served"}[1h]))
  / sum(rate(gen_api_requests_total{status="success"}[1h]))
```
**Alert threshold: page the owner when > 0.20 sustained for 1h.**

**2. How healthy is the engine fleet?**
```promql
gen_api_healthy_engines                          # per category, now
rate(gen_api_engine_probes_total{outcome="fail"}[1h])  # per-engine failure rate
```
Alert when `gen_api_healthy_engines{category="general"} < 2`.

**3. Are results degrading even when they return 200?**
```promql
sum(rate(gen_api_degraded_responses_total[1h]))
  / sum(rate(gen_api_requests_total{status="success"}[1h]))
histogram_quantile(0.5, rate(gen_api_quality_score_bucket[6h]))  # median quality
```

**4. Is the egress under pressure?**
```promql
rate(gen_api_cache_requests_total{result="hit"}[1h])
  / rate(gen_api_cache_requests_total[1h])            # cache hit rate (higher = less egress)
histogram_quantile(0.95, rate(gen_api_outbound_wait_seconds_bucket[15m]))  # queue depth
histogram_quantile(0.95, rate(gen_api_provider_latency_seconds_bucket[1h]))
```

---

## Procedures

### Respond to a block spike

Symptoms: `gen_api_provider_requests_total{provider="genxng",outcome="error"}`
climbing, fall-through rate climbing, `healthy_engines` dropping, users
reporting thin results.

1. Confirm it's upstream blocking, not searxng itself:
   `docker compose logs searxng --tail 50` (look for 429/CAPTCHA mentions),
   and `curl "http://localhost:8081/search?q=test&format=json"`.
2. Cut egress volume immediately:
   - halve `OUTBOUND_QPS` in `.env`, `docker compose up -d api`;
   - raise cache TTLs temporarily (`CACHE_TTL='{"search": 86400}'`);
   - raise `ENGINE_PROBE_INTERVAL` (probes are outbound traffic too).
3. Let quality fall-through carry the load (verify the commercial key has
   credits — this is exactly what the fallback slot is for).
4. When the spike passes (hours to a day), re-run the ceiling probe
   off-peak and set `OUTBOUND_QPS` from its new number.

### Re-enable or disable an engine

Evidence-based path (preferred):
```bash
python scripts/engine_probe.py --apply     # regenerates the engines section
docker compose restart searxng
```
Manual override: edit the probe-managed block in `searxng/settings.yml`
(between the `engine-probe: BEGIN/END` markers), flip `disabled:`, restart
searxng. The next `--apply` run will overwrite manual edits — prefer fixing
the probe's endpoint map instead.

The in-app quarantine (`gen_api_healthy_engines`) is automatic and
self-recovering; it needs no operator action.

### Weekly probes (through the corporate proxy, on the app server)

```bash
python scripts/ceiling_probe.py --rates 0.2,0.5,1,2 --step-seconds 60   # off-peak; provokes a block at the end
python scripts/engine_probe.py --apply
```
Update `OUTBOUND_QPS` from the ceiling report (it suggests 25% headroom).

### API keys and credits

```bash
docker compose exec api python -m app.cli create-key --name <consumer> --credits 10000
docker compose exec postgres psql -U gen -d gen -c "SELECT name, credits FROM api_keys;"
docker compose exec postgres psql -U gen -d gen -c "UPDATE api_keys SET credits = credits + 10000 WHERE name = '<consumer>';"
docker compose exec postgres psql -U gen -d gen -c "UPDATE api_keys SET active = false WHERE name = '<consumer>';"
```

### Who used what (usage audit)

```sql
SELECT vertical, provider, cached, count(*), sum(credits)
FROM usage_log WHERE created_at > now() - interval '7 days'
GROUP BY 1, 2, 3 ORDER BY 4 DESC;
```
Logs are ICT-safe: query text is never stored or logged (hashes only).

### Sensitivity policy changes

Edit `policy/sensitive.yml` (versioned in git — commit the change), then
`docker compose up --build -d api`. Verify with a matching test query: it
must return `403 {"policyBlocked": true}`. Blocks are visible in
`gen_api_policy_blocked_total{category}`.

### Restart / redeploy

```bash
.\run.ps1              # Windows one-shot (build + start + health-wait)
docker compose up --build -d      # any platform
docker compose logs api --tail 50 # structured JSON, one line per request
```

---

## Fallback provider economics (plan 5.1)

The fallback slot is **bursty and low-average**: quiet in good months,
spiking during breakage weeks. Choose a billing model that matches:

- **Fits:** prepaid pay-as-you-go credits (e.g. Serper prepaid, DataForSEO
  balance) — buy a buffer, it drains only when GenXNG degrades.
- **Punishes:** monthly-bucket use-it-or-lose-it subscriptions — you either
  over-provision every month or blow the bucket mid-incident.

Integration cost: any Gen-wire-compatible endpoint is config only
(`COMMERCIAL_BASE_URL` + `COMMERCIAL_API_KEY`). A provider with a different
wire format (e.g. DataForSEO) needs a small adapter subclass of
`CommercialProvider` — roughly a day, not a rewrite, because every provider
normalizes into the same canonical schema.

Watch the fall-through rate (question 1): it is also your fallback bill
forecast.
