#!/usr/bin/env python3
# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0
"""
reset.py — Reset all demo flags to safe defaults before going on stage.

Usage:  python3 src/talk-loadgen/reset.py
        make reset
"""

import json
import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).parent.parent.parent
FLAGD_JSON = REPO_ROOT / "src" / "flagd" / "demo.flagd.json"

CHAOS_FLAGS = [
    "adFailure", "adHighCpu", "adManualGc", "cartFailure",
    "failedReadinessProbe", "kafkaQueueProblems", "llmInaccurateResponse",
    "llmRateLimitError", "loadGeneratorFloodHomepage", "paymentFailure",
    "paymentUnreachable", "productCatalogFailure", "recommendationCacheFailure",
]


def load():
    with open(FLAGD_JSON) as f:
        return json.load(f)


def save(d):
    with open(FLAGD_JSON, "w") as f:
        json.dump(d, f, indent=2)


def set_default(d, key, variant):
    d["flags"][key]["defaultVariant"] = variant
    print(f"  ✓  {key} → {variant}")


def main():
    print()
    print("━" * 48)
    print("  Resetting demo flags to pre-stage defaults")
    print("━" * 48)

    d = load()

    # Demo 1 — Canary: 100% v1, no targeting, no errors
    d["flags"]["productCatalogCanary"].pop("targeting", None)
    set_default(d, "productCatalogCanary", "v1")
    set_default(d, "productCatalogV2Severity", "none")

    # Demo 2 — AI model
    set_default(d, "productSummaryModel", "model-a")

    # Demo 3 — Recommendation A/B: remove targeting so all users get popularity
    d["flags"]["recommendationAlgorithm"].pop("targeting", None)
    set_default(d, "recommendationAlgorithm", "popularity")

    # Chaos flags
    for flag in CHAOS_FLAGS:
        if flag in d["flags"]:
            set_default(d, flag, "off")

    # emailMemoryLeak has variant "off" but value 0
    if "emailMemoryLeak" in d["flags"]:
        set_default(d, "emailMemoryLeak", "off")

    # imageSlowLoad has variant "off"
    if "imageSlowLoad" in d["flags"]:
        set_default(d, "imageSlowLoad", "off")

    save(d)

    print()
    print("✅  All flags reset. flagd hot-reloads within ~1s.")
    print(f"    Dashboard: http://localhost:8080/grafana/")
    print(f"    Flags UI:  http://localhost:8080/feature/")
    print()


if __name__ == "__main__":
    main()
