# OpenFeature + OpenTelemetry talk demo — flag scenarios

This document is the runbook for the three feature-flag scenarios used in
the **"Observability and Feature Flagging"** talk. It complements
[demo.flagd.json](demo.flagd.json), where the flag definitions live.

The talk's framing: Dynatrace acquired DevCycle (release safety), Datadog
acquired Eppo (experimentation). Neither press release mentions
OpenTelemetry or feature-flag semantic conventions — yet that is what makes
the OpenFeature + OTel combination the only **vendor-neutral** path through
this convergence.

The three flags below each demonstrate one pillar of that story.

## How SemConv attributes get on every span

The OpenFeature OpenTelemetry contrib hooks are registered globally during
service startup so that **every** flag evaluation in the wired services
attaches `feature_flag.key`, `feature_flag.variant` and
`feature_flag.provider_name` (per
[OTel SemConv](https://opentelemetry.io/docs/specs/semconv/feature-flags/))
to the active span.

| Service | Language | Hook registered? |
|---|---|---|
| `product-catalog` | Go | ✅ `otelhooks.NewTracesHook()` |
| `recommendation` | Python | ✅ `TracingHook()` |
| `llm` | Python | ✅ `TracingHook()` (added in this branch) |

This is the "OpenFeature contributed SemConv to OpenTelemetry" point made
concrete: no manual span instrumentation is needed inside the flag
evaluation path.

---

## Scenario 1 — Recommendation algorithm A/B test

**Pillar:** Datadog / Eppo — experimentation tied to business outcomes.
**Flag:** `recommendationAlgorithm` (string).
**Variants:** `popularity` (default) | `collaborative` | `personalized`.
**Service:** `src/recommendation/recommendation_server.py`.

**Targeting in flagd:**
- `userTier == "premium"` → `personalized`
- otherwise fractional 50/50 between `popularity` and `collaborative`.

**What the code does:** `get_product_list` calls
`get_recommendation_algorithm()` (a thin wrapper around the OpenFeature
client's `get_string_value`) and selects a different ordering strategy per
variant. The active span gets `app.recommendation.algorithm` and — via the
TracingHook — the SemConv `feature_flag.*` attributes.

**On stage:**
1. Open Grafana dashboard (or Jaeger trace view).
2. Filter by `feature_flag.key=recommendationAlgorithm`.
3. Show traces split per variant. Note that no per-service code
   instrumented this — the hook did.
4. Edit targeting in `flagd-ui` (e.g. shift the fractional split to 80/20)
   and watch the variant distribution change live.

**Still to wire (next steps):**
- Frontend `client.track("checkout_completed", { value, currency })` calls
  to feed business-impact dashboards. See
  `src/frontend/providers/Cart.provider.tsx` and the checkout flow.
- A Grafana panel comparing conversion / AOV per variant.

---

## Scenario 2 — Product-catalog progressive rollout (canary)

**Pillar:** Dynatrace / DevCycle — risk reduction, progressive delivery.
**Flag:** `productCatalogCanary` (string).
**Variants:** `v1` (default) | `v2`, with **fractional rollout** — defaults
to 95% / 5% in `demo.flagd.json`.
**Service:** `src/product-catalog/main.go` (Go SDK + OTel TracesHook
already wired).

**On stage:**
1. Confirm baseline: 5% of traffic carries `feature_flag.variant=v2` on
   spans.
2. In flagd-ui, edit the targeting rule to step the rollout up
   (5% → 25% → 50%).
3. Filter spans by `feature_flag.variant=v2` to isolate the canary cohort
   end-to-end (product-catalog → checkout → frontend).
4. If a regression is observed, edit back to 5% — recovery is instant, no
   redeploy.

**Talking point on the slide:** this is exactly Dynatrace's framing of
"health-driven feature control." Today the flip is manual; tomorrow's
extension is autonomous. The SemConv attributes are what make either
possible without per-vendor lock-in.

**Still to wire (next steps):**
- A `v2` code-path branch in `product-catalog/main.go` that is observably
  different (e.g. extra latency, slightly different ordering, or a
  controlled error rate). The flag is read; the behavioural fork is the
  remaining task.

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
