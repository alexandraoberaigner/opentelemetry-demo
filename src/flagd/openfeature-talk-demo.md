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
