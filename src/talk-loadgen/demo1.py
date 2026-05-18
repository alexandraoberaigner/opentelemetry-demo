#!/usr/bin/env python3
# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0
"""
demo1.py — Demo 1: Product Catalog Canary Rollout

Interactive flag escalation. Press Enter to advance each step.
Each step increases both v2 rollout percentage and error severity together.

  Step 0  Baseline     5% v2   severity=none     (0% errors)
  Step 1  Escalate    25% v2   severity=low      (15% errors)
  Step 2  Escalate    50% v2   severity=high     (40% errors)
  Step 3  Critical    75% v2   severity=critical  (75% errors)
  Step 4  Rollback     0% v2   severity=none

Usage:  python3 src/talk-loadgen/demo1.py
        make demo1
"""

import json
import pathlib
import signal
import subprocess
import sys
import time
import webbrowser

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


def set_canary(d, v2_pct):
    v1_pct = 100 - v2_pct
    if v2_pct == 0:
        d["flags"]["productCatalogCanary"].pop("targeting", None)
        d["flags"]["productCatalogCanary"]["defaultVariant"] = "v1"
        print(f"  ✓  productCatalogCanary → 100% v1 (targeting removed)")
    else:
        d["flags"]["productCatalogCanary"]["targeting"] = {
            "fractional": [
                {"var": "$flagd.targetingKey"},
                ["v1", v1_pct],
                ["v2", v2_pct],
            ]
        }
        d["flags"]["productCatalogCanary"]["defaultVariant"] = "v1"
        print(f"  ✓  productCatalogCanary → {v2_pct}% v2 / {v1_pct}% v1")


def start_k6():
    global k6_proc
    print()
    print("  Starting k6 demo1 (product-catalog traffic)...")
    subprocess.run(["pkill", "-f", "k6 run.*SCENARIO"], capture_output=True)
    time.sleep(1)
    log = open("/tmp/k6-demo1.log", "w")
    k6_proc = subprocess.Popen(
        ["k6", "run", "-e", "SCENARIO=demo1", str(LOADGEN_JS)],
        stdout=log, stderr=log,
    )
    print(f"  k6 PID {k6_proc.pid} — log: /tmp/k6-demo1.log")
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
    print("║  Demo 1 — Product Catalog Canary Rollout     ║")
    print("╚══════════════════════════════════════════════╝")
    dashboard_url = "http://localhost:8080/grafana/d/feature-flag-recommendation?from=now-5m&to=now&refresh=5s"
    print()
    print(f"  Dashboard: {dashboard_url}")
    print("  Flags UI:  http://localhost:8080/feature/")
    webbrowser.open(dashboard_url)

    # ── Baseline ──────────────────────────────────────────────────────────────
    step("0", "4", "Baseline — resetting flags, starting load")
    d = load()
    set_canary(d, 0)
    set_default(d, "productCatalogV2Severity", "none")
    save(d)
    start_k6()
    wait_enter("Baseline set. 100% v1, 0% errors. Dashboard shows green v1 line only.")

    # ── Step 1: 5% v2, none ───────────────────────────────────────────────────
    step("1", "4", "5% v2 canary — no errors yet")
    d = load()
    set_canary(d, 5)
    set_default(d, "productCatalogV2Severity", "none")
    save(d)
    wait_enter("5% of users on v2. p95 barely moves. Small yellow sliver in traffic split.")

    # ── Step 2: 25% v2, low ───────────────────────────────────────────────────
    step("2", "4", "25% v2 + low severity (15% errors)")
    d = load()
    set_canary(d, 25)
    set_default(d, "productCatalogV2Severity", "low")
    save(d)
    wait_enter(
        "Yellow latency rising. Red errors appearing (~15%).\n"
        "  Jaeger: feature_flag.key=productCatalogCanary feature_flag.result.variant=v2"
    )

    # ── Step 3: 50% v2, high ──────────────────────────────────────────────────
    step("3", "4", "50% v2 + high severity (40% errors)")
    d = load()
    set_canary(d, 50)
    set_default(d, "productCatalogV2Severity", "high")
    save(d)
    wait_enter("Half your users on v2. p95 clearly elevated. 40% error rate. SLO is breaching.")

    # ── Step 4: 75% v2, critical ──────────────────────────────────────────────
    step("4", "4", "75% v2 + critical severity (75% errors)")
    d = load()
    set_canary(d, 75)
    set_default(d, "productCatalogV2Severity", "critical")
    save(d)
    wait_enter("75% of users, 75% errors. Time to roll back. Press Enter to execute.")

    # ── Rollback ──────────────────────────────────────────────────────────────
    print()
    print("━" * 48)
    print("  ROLLBACK — one flag flip")
    print("━" * 48)
    d = load()
    set_canary(d, 0)
    set_default(d, "productCatalogV2Severity", "none")
    save(d)
    print()
    print("  ✅  Rolled back. 100% v1, 0% errors.")
    print("      Watch all panels recover in ~30s.")
    print()
    print('  "Rollback was one flag flip. No deploy. No restart."')
    print('  "Remember the hook — the next two demos use the exact same one."')
    print()


if __name__ == "__main__":
    main()
