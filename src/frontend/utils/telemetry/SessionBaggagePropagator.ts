// Copyright The OpenTelemetry Authors
// SPDX-License-Identifier: Apache-2.0

import {
  Context,
  propagation,
  TextMapGetter,
  TextMapPropagator,
  TextMapSetter,
} from '@opentelemetry/api';
import { W3CBaggagePropagator } from '@opentelemetry/core';

/**
 * Wraps W3CBaggagePropagator so that `session.id` is added to outgoing
 * baggage on every request. Backend services that read OTel baggage can then
 * attach the same `session.id` to their spans, letting us join flag-evaluation
 * spans (server-side) and tracking spans (frontend) by user.
 */
export class SessionBaggagePropagator implements TextMapPropagator {
  private readonly inner = new W3CBaggagePropagator();
  private readonly getSessionId: () => string | undefined;

  constructor(getSessionId: () => string | undefined) {
    this.getSessionId = getSessionId;
  }

  inject(context: Context, carrier: unknown, setter: TextMapSetter): void {
    const sessionId = this.getSessionId();
    if (sessionId) {
      const baggage = propagation.getBaggage(context) ?? propagation.createBaggage();
      const updated = baggage.setEntry('session.id', { value: sessionId });
      context = propagation.setBaggage(context, updated);
    }
    this.inner.inject(context, carrier, setter);
  }

  extract(context: Context, carrier: unknown, getter: TextMapGetter): Context {
    return this.inner.extract(context, carrier, getter);
  }

  fields(): string[] {
    return this.inner.fields();
  }
}
