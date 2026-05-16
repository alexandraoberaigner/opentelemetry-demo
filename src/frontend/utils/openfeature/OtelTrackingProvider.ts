// Copyright The OpenTelemetry Authors
// SPDX-License-Identifier: Apache-2.0

import type {EvaluationContext, TrackingEventDetails,} from '@openfeature/react-sdk';
import {SpanStatusCode, trace} from '@opentelemetry/api';
import {FlagdWebProvider} from "@openfeature/flagd-web-provider";

/**
 * Wraps another OpenFeature provider so that calls to
 * `OpenFeature.getClient().track(...)` emit an OpenTelemetry span. All flag
 * resolution is delegated to the inner provider untouched.
 *
 * The OF spec defines tracking as a provider-level extension (the `track`
 * method on `Provider`), not a hook. flagd's web provider does not implement
 * it, so without this wrapper `client.track(...)` silently no-ops.
 */
export class OtelTrackingProvider extends FlagdWebProvider {

  track(eventName: string, context?: EvaluationContext, details?: TrackingEventDetails): void {
    const tracer = trace.getTracer('openfeature-tracking');
    const span = tracer.startSpan(`openfeature.track ${eventName}`);
    span.setAttribute('feature_flag.tracking.event_name', eventName);

    if (context?.targetingKey) {
      span.setAttribute('feature_flag.context.targeting_key', context.targetingKey);
    }

    if (details) {
      if (typeof details.value === 'number') {
        span.setAttribute('feature_flag.tracking.value', details.value);
      }
      for (const [k, v] of Object.entries(details)) {
        if (k === 'value' || v === null || v === undefined) continue;
        const attrKey = `feature_flag.tracking.${k}`;
        if (typeof v === 'string' || typeof v === 'number' || typeof v === 'boolean') {
          span.setAttribute(attrKey, v);
        } else {
          span.setAttribute(attrKey, JSON.stringify(v));
        }
      }
    }

    span.setStatus({ code: SpanStatusCode.OK });
    span.end();
  }
}
