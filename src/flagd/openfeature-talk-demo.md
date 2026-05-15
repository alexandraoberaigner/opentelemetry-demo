# OpenFeature + OpenTelemetry talk demo — runbook

This is the stage runbook for the three feature-flag scenarios in the
**"Observability and Feature Flagging"** talk. Flag definitions live in
[demo.flagd.json](demo.flagd.json).

## Start the demo

```bash
make start                   # builds + starts the full stack (~2 min)
make loadgen-background      # warm up all services (runs 10 min, Ctrl+C when ready)
```

Open four tabs:
| Tab | URL |
|---|---|
| Webshop | http://localhost:8080 |
| Grafana | http://localhost:8080/grafana/ → "Feature Flag — Observability Dashboard" |
| Jaeger | http://localhost:8080/jaeger/ui |
| flagd-ui | http://localhost:8080/feature/ |

### Load generator

The locust load generator is **disabled by default** via `.env.override`:

```
LOCUST_AUTOSTART=
```

This starts the locust container (so the Locust UI is available at
http://localhost:8080/loadgen/) but does not generate any traffic.
Traffic is driven entirely by **k6** (`brew install k6`):

```bash
make loadgen-background   # warm up all services while setting up (~10 min, Ctrl+C when ready)
make loadgen-demo1        # Demo 1 burst — recommendation + checkout flows (~2.5 min)
make loadgen-demo2        # Demo 2 burst — product catalog canary traffic (~2 min)
```

To re-enable locust traffic (e.g. for testing outside the talk), set
`LOCUST_AUTOSTART=true` in `.env.override`.

## How SemConv attributes get on every span

The OTel `TracingHook` is registered globally in each service:

```python
api.add_hooks([TracingHook()])   # recommendation, llm
```
```go
openfeature.AddHooks(otelhooks.NewTracesHook())  // product-catalog
```

Every flag evaluation then automatically attaches `feature_flag.key`,
`feature_flag.variant`, and `feature_flag.provider_name` to the active
span — no per-evaluation instrumentation code needed.

The collector's `transform/sanitize_spans` processor additionally promotes
these from **span events** (where the TracingHook places them) to **span
attributes** so the spanmetrics connector can use them as metric dimensions.

---

## Demo 1 — Recommendation A/B test (~4 min)

**Flag:** `recommendationAlgorithm` · **Service:** `recommendation` (Python)

**Story:** *"We added a feature flag. We didn't write any telemetry code.
Let's see what we get for free."*

### Step 1 — Show the hook in Jaeger (1 min)

1. Jaeger → service `recommendation` → Find Traces
2. Open any `oteldemo.RecommendationService/ListRecommendations` trace
3. Expand the span → **Events** tab → `feature_flag.evaluation` event:
   - `feature_flag.key = recommendationAlgorithm`
   - `feature_flag.result.variant = popularity` (or `personalized`)
4. *"One line: `api.add_hooks([TracingHook()])`. That's it."*

### Step 2 — Per-variant metrics in Grafana (1 min)

1. Grafana → **Feature Flag — Recommendation A/B Test** dashboard
2. Show:
   - **Impressions by Variant** — stacked traffic split
   - **p95 Latency by Variant** — `personalized` is visibly higher (~100ms vs ~20ms)
3. *"Span events → collector transform → spanmetrics → Prometheus. All YAML,
   no code."*

### Step 3 — Business impact: AOV by variant (1 min)

1. Scroll to **AOV by Recommendation Variant** table
2. Show: `personalized` has ~2× higher AOV than `popularity`
3. *"The recommendation service logs the user session ID and variant. The
   checkout service logs the same session ID and order amount. OpenSearch
   joins them with a PPL query. No checkout code knows about the flag."*

### Step 4 — Live rollout change (1 min)

1. flagd-ui → `recommendationAlgorithm` → change default to `personalized`
2. Watch Grafana: impressions panel shifts, latency panel shifts
3. *"No deploy. No restart. The flag changed — the hook reflects it
   automatically on every span."*

**Reset:** set `recommendationAlgorithm` back to original defaults.

---

## Demo 2 — Product-catalog progressive rollout (~3 min)

**Flag:** `productCatalogCanary` · **Service:** `product-catalog` (Go)

**Story:** *"Safe rollout of a new catalog version — observable regression,
instant rollback."*

### What v2 does

Two flags give full on-stage control:

| Flag | Default | Role |
|---|---|---|
| `productCatalogCanary` | 95/5 | Controls *who* gets v2 (fractional rollout by session ID) |
| `productCatalogV2Severity` | `none` (0%) | Controls *how bad* v2 is: `none`=0%, `low`=15%, `high`=40%, `critical`=75% |

- **+150 ms latency** always present on v2 — visible from the first v2 spans
- **Error rate** is 0% by default — step up severity as you increase rollout %

### Step sequence

| Step | `productCatalogCanary` v2% | `productCatalogV2Severity` | What to see |
|---|---|---|---|
| Baseline | 5% | `none` | Tiny red latency blip — looks healthy |
| Step 1 | 25% | `none` | Latency spike visible (red ~170ms). No errors yet — *"just slower"* |
| Step 2 | 25% | `low` | Errors start appearing. *"Uh oh."* |
| Step 3 | 50% | `high` | More errors. *"This is getting bad."* |
| Step 4 | 75% | `critical` | Errors dominate. *"SLO breach. Roll back now."* |
| Rollback | 5% | `none` | Both panels recover in ~30 seconds |

### Steps

1. `make loadgen-demo2` — start traffic (keep running during the demo)
2. **Grafana** → "Feature Flag — Observability Dashboard" → scroll to Demo 2 row
3. Confirm baseline: green v1 lines, tiny red v2 blip, zero errors
4. **flagd-ui** → `productCatalogCanary` → step v2 to 25%
   - **p95 Latency**: red line clearly above green
   - **Error Rate**: still clean — *"Hmm, slower but no errors yet"*
5. **flagd-ui** → `productCatalogV2Severity` → set to `low`
   - Errors appear — *"There it is"*
6. Step canary to 50% + severity to `high`
   - Errors growing — *"Getting worse"*
7. Step canary to 75% + severity to `critical`
   - Errors dominate — *"SLO breach. Roll back."*
8. Roll back: `productCatalogCanary` to 5%, `productCatalogV2Severity` to `none`
   - Both panels recover within ~30 seconds
9. *"No deploy. No restart. The flag key is already on every span — that's
   the SemConv payoff."*

**Reset:** `productCatalogCanary` = 95/5, `productCatalogV2Severity` = `none`.

---

## Demo 3 — Multi-model AI summary (~3 min)

**Flag:** `productSummaryModel` · **Service:** `llm` (Python)

**Story:** *"Compare two AI models on cost and latency. Kill the bad one
instantly."*

**Still to wire:**
- Read `productSummaryModel` in `app.py` and branch behaviour (different
  simulated latency / token cost per variant)
- Per-variant counters: `llm.tokens.total{model=…}`,
  `llm.requests.errors{model=…}`

### Steps (once wired)

1. Show baseline traffic on `model-a` — per-variant latency / cost panels
2. flagd-ui → flip to `model-b` — watch metrics shift
3. Enable `llmRateLimitError=on` — errors appear, isolated to `model-b`
4. Flip flag to `off` (kill switch) — incident contained, no redeploy

*"The same SemConv attributes that power the A/B test also power the
incident response — that's the OpenFeature + OTel payoff."*

---

## Validation checklist (before going on stage)

- [ ] `make start` completes and all containers are healthy
- [ ] `feature_flag.key` / `feature_flag.variant` visible on
      `recommendation` spans in Jaeger
- [ ] Grafana dashboard shows data in all 4 panels (allow 5 min after start)
- [ ] flagd-ui targeting edits propagate within ~5 seconds
- [ ] AOV table shows data for at least 2 variants
- [ ] All flags reset to defaults before stepping on stage

## Implementation notes (Demo 1)

Changes made to the base OTel demo:

| File | Change |
|---|---|
| `src/recommendation/recommendation_server.py` | `derive_user_tier()`, `EvaluationContext` with `userTier`, structured log with `app.user.id` + `app.recommendation.algorithm`, `app.user.*` span attributes, 50–120ms latency simulation for `personalized` |
| `src/recommendation/metrics.py` | `app_recommendations_algorithm_counter` per-variant counter |
| `src/checkout/main.go` | `app.user.id` added to "order placed" log (enables session ID join) |
| `src/otel-collector/otelcol-config.yml` | Spanevent→span attribute transform for `feature_flag.*`; `feature_flag.key` / `feature_flag.variant` as spanmetrics dimensions; `api_version: 1.42` bug fix |
| `src/load-generator/locustfile.py` | Checkout flow calls recommendations first (same session ID); variant-dependent conversion rates (popularity 40%, collaborative 55%, personalized 85%) |
| `src/grafana/provisioning/dashboards/demo/feature-flag-dashboard.json` | New dashboard: impressions by variant, p95 latency, checkout rate, AOV by variant via OpenSearch PPL join |
