#!/usr/bin/env python3
# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0
"""
demo3.py — Demo 3: Recommendation A/B Test

Interactive flag flip sequence. Press Enter to advance each step.

  Step 0  Baseline  recommendationAlgorithm=popularity
  Step 1  Flip      recommendationAlgorithm=personalized
  Step 2  AOV beat  (narration — no flag change)
  Opt.    Rollback  recommendationAlgorithm=popularity

Usage:  python3 src/talk-loadgen/demo3.py
        make demo3
"""

import json
import pathlib
import signal
import subprocess
import sys
import time

REPO_ROOT = pathlib.Path(__file__).parent.parent.parent
FLAGD_JSON = REPO_ROOT / "src" / "flagd" / "demo.flagd.json"
LOADGEN_JS = pathlib.Path(__file__).parent / "loadgen.js"

k6_proc = None


def load():
    with open(FLAGD_JSON) as f:
        return json.load(f)


def save(d):
    with open(FLAGD_JSON, "w") as f:
        json.dump(d, f, indent=2)


def set_default(d, key, variant):
    d["flags"][key]["defaultVariant"] = variant
    print(f"  ✓  {key} → {variant}")


def start_k6():
    global k6_proc
    print()
    print("  Starting k6 demo3 (recommendation traffic)...")
    subprocess.run(["pkill", "-f", "k6 run.*SCENARIO"], capture_output=True)
    time.sleep(1)
    log = open("/tmp/k6-demo3.log", "w")
    k6_proc = subprocess.Popen(
        ["k6", "run", "-e", "SCENARIO=demo3", str(LOADGEN_JS)],
        stdout=log, stderr=log,
    )
    print(f"  k6 PID {k6_proc.pid} — log: /tmp/k6-demo3.log")
    time.sleep(2)


def step(num, total, title):
    print()
    print("━" * 48)
    print(f"  STEP {num}/{total} — {title}")
    print("━" * 48)


def wait_enter(hint):
    print()
    print(f"  → {hint}")
    print()
    input("  Press Enter to continue...")


def cleanup(sig=None, frame=None):
    if k6_proc:
        k6_proc.terminate()
    sys.exit(0)


signal.signal(signal.SIGINT, cleanup)


def main():
    print()
    print("╔══════════════════════════════════════════════╗")
    print("║  Demo 3 — Recommendation A/B Test           ║")
    print("╚══════════════════════════════════════════════╝")
    print()
    print("  Dashboard: http://localhost:8080/grafana/d/feature-flag-recommendation?from=now-5m&to=now&refresh=5s")
    print("  Jaeger:    http://localhost:8080/jaeger/ui")

    # ── Baseline ──────────────────────────────────────────────────────────────
    step("0", "2", "Baseline — resetting flags, starting load")
    d = load()
    # Clear any canary state left over from demo1
    d["flags"]["productCatalogCanary"].pop("targeting", None)
    d["flags"]["productCatalogCanary"]["defaultVariant"] = "v1"
    set_default(d, "productCatalogV2Severity", "none")
    set_default(d, "recommendationAlgorithm", "popularity")
    save(d)
    start_k6()
    print()
    print("  NOTE: if the dashboard still shows v2 traffic, it is historical")
    print("  data from demo1. Wait ~30s for the [30s] rate window to flush.")
    wait_enter(
        "Baseline: all users on 'popularity'.\n"
        "  p95 low. Single variant in impressions chart. AOV table loading."
    )

    # ── Step 1: Flip to personalized ─────────────────────────────────────────
    step("1", "2", "Flip to personalized")
    d = load()
    set_default(d, "recommendationAlgorithm", "personalized")
    save(d)
    wait_enter(
        "Flipped. Watch impressions shift to 'personalized'.\n"
        "  p95 rising (~200ms vs ~20ms).\n"
        "  AOV table updating in ~30s."
    )

    # ── Step 2: AOV narration beat ────────────────────────────────────────────
    step("2", "2", "The business insight — AOV table")
    print()
    print("  Open the AOV table in the dashboard.")
    print("  'personalized' drives larger baskets.")
    print()
    print("  The checkout service has no idea the flag exists.")
    print("  client.Track('checkout.completed') → otelTrackingProvider → OTel log.")
    print("  PPL joins recommendation served + checkout.completed on app.user.id.")
    print()
    input("  Press Enter when the AOV gap is visible...")

    print()
    print('  "Personalized drives larger baskets."')
    print('  "The checkout service has no idea the flag exists."')
    print('  "One open standard. All use cases."')
    print()

    # ── Optional rollback ─────────────────────────────────────────────────────
    answer = input("  Roll back to popularity? (y/N) ").strip().lower()
    if answer == "y":
        d = load()
        set_default(d, "recommendationAlgorithm", "popularity")
        save(d)
        print("  ✓  Rolled back to popularity.")

    print()
    print("  ✅  Demo 3 complete.")
    print()


if __name__ == "__main__":
    main()
