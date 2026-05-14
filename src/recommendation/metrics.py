#!/usr/bin/python

# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

def init_metrics(meter):

    # Recommendations counter
    app_recommendations_counter = meter.create_counter(
        'app_recommendations_counter', unit='recommendations', description="Counts the total number of given recommendations"
    )

    # Per-algorithm recommendations counter — allows Grafana to split by variant
    app_recommendations_algorithm_counter = meter.create_counter(
        'app_recommendations_algorithm_counter', unit='recommendations',
        description="Counts recommendations split by the feature-flag-selected algorithm variant"
    )

    rec_svc_metrics = {
        "app_recommendations_counter": app_recommendations_counter,
        "app_recommendations_algorithm_counter": app_recommendations_algorithm_counter,
    }

    return rec_svc_metrics
