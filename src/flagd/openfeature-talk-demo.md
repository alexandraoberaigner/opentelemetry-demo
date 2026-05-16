# OpenFeature + OpenTelemetry talk demo

Flag definitions for the three demo scenarios used in the
**"Observability and Feature Flagging"** talk live in
[demo.flagd.json](demo.flagd.json).

## Stage runbook

The full runbook (setup, load generator commands, per-demo step sequences,
timing guide, validation checklist) lives in the talk repo:

**[talk-observability-and-feature-flagging / docs/demo-runbook.md](https://github.com/alexandraoberaigner/talk-observability-and-feature-flagging/blob/feat/talk-foundation/docs/demo-runbook.md)**

## Flag defaults (for reset before going on stage)

| Flag | Default variant | Purpose |
|---|---|---|
| `recommendationAlgorithm` | `popularity` | Demo 1 — recommendation A/B test |
| `productCatalogCanary` | `v1` (95/5 fractional) | Demo 2 — canary rollout |
| `productCatalogV2Severity` | `none` | Demo 2 — controls v2 error rate |
| `productSummaryModel` | `model-a` | Demo 3 — AI model comparison |

## Implementation notes

### What this branch adds (over the base OTel demo)

| Component | Change |
|---|---|
| `recommendation_server.py` | `EvaluationContext` with `userTier`, structured log with `app.user.id` |
| `checkout/main.go` | `app.user.id` on "order placed" log (enables session-based AOV join) |
| `product-catalog/main.go` | `productCatalogCanary` flag evaluation, v2 regression simulation |
| `otelcol-config.yml` | Spanevent→span attribute transform, spanmetrics dimensions, 10s flush |
| `prometheus-config.yaml` | `scrape_interval: 15s` for responsive dashboards |
| `grafana/.../feature-flag-dashboard.json` | Combined Demo 1 + Demo 2 dashboard |
| `talk-loadgen/loadgen.js` | k6 load generator with `background`, `demo1`, `demo2` scenarios |
| `Makefile` | `loadgen-background`, `loadgen-demo1`, `loadgen-demo2` targets |

---

## Scenario 3 — Multi-model AI summary

**Pillar:** Both Datadog (multi-AI-model experimentation) and Dynatrace
(incident response / kill switch).
**Flag:** `productSummaryModel` (string).
**Variants:** `off` | `model-a` (default) | `model-b`.
**Service:** `src/llm/app.py`.

**This branch adds:**
- `TracingHook()` to the LLM service (it was missing — boolean flag
  evaluations there did not previously attach SemConv attributes).
- `get_product_summary_model()` helper.
- `openfeature-hooks-opentelemetry` in `requirements.txt`.
- **Variant branching in `chat_completions`** (`src/llm/app.py`):
  - `off` → returns HTTP 503 (kill switch — the AI summary feature is
    disabled end-to-end without a redeploy).
  - `model-a` → default path.
  - `model-b` → simulates a degraded experimental model: 300–800 ms
    artificial latency and a ~10% chance of HTTP 500.
- The response `model` field echoes the resolved variant. The
  `product-reviews` service is already auto-instrumented with
  [`opentelemetry-instrumentation-openai-v2`](https://pypi.org/project/opentelemetry-instrumentation-openai-v2/),
  so the per-call span on the LLM client carries
  `gen_ai.response.model={model-a|model-b}` plus token usage and span
  status — that is what the per-variant panel filters on.
- **Frontend `summary_helpful_clicked` tracking event**
  (`src/frontend/components/ProductReviews/ProductReviews.tsx`): 👍 / 👎
  buttons under the AI response call
  `OpenFeature.getClient().track('summary_helpful_clicked', { value: 1|0, helpful, productId })`,
  feeding the engagement signal for the A/B.

> Why the variant rides on `gen_ai.response.model` instead of the
> SemConv `feature_flag.*` attributes: the LLM service is intentionally
> uninstrumented (it is the "black-box LLM"). The `TracingHook` has no
> active span to attach to inside it, so we propagate the variant back
> to the caller via the response model field, where the auto-instrumented
> OpenAI client span captures it. The `feature_flag.*` SemConv story is
> told by scenarios 1 and 2, where the services are first-class
> instrumented.

**On stage closing beat:**
1. Show baseline traffic on `model-a`.
2. Flip `productSummaryModel=model-b` in flagd-ui to start the
   experiment — show per-variant latency / cost / engagement panels.
3. Combine with the existing `llmRateLimitError=on` to simulate `model-b`
   degrading.
4. Flip the flag to `off` (kill switch) — incident contained without
   redeploy.

This single example covers Datadog's "compare multiple models on
engagement vs cost" and Dynatrace's "act immediately when issues arise."

**Still to wire (next steps):**
- A Grafana / vendor panel that filters by `gen_ai.response.model` and
  shows per-variant latency p95, error rate, and the engagement event
  count from `summary_helpful_clicked`.

---

## End-to-end runbook for stage practice

1. `docker compose up` (or the Makefile target) and wait for flagd-ui to
   be reachable.
2. Browse the astronomy shop, generate baseline traffic via load-generator.
3. Open Grafana dashboards filtered by `feature_flag.key`.
4. For each scenario above, flip the flag in flagd-ui and narrate what is
   happening on the dashboard. Time-box ~3 minutes per scenario.
5. Reset all flags to defaults at the end.

## Validation checklist before going on stage

- [ ] `feature_flag.key` and `feature_flag.variant` visible on
      `recommendation`, `product-catalog`, and `llm` spans in Jaeger /
      Grafana Tempo / vendor backend.
- [ ] Targeting edits in flagd-ui propagate within seconds.
- [ ] Each flag has a "boring default" so the demo never starts in a
      broken state.
- [ ] Tracking events (frontend) appear as span events / metrics — see
      next-steps in scenarios 1 and 3.
