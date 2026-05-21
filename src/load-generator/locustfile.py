#!/usr/bin/python

# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

import json
import os
import random
import uuid
import logging

from locust import HttpUser, task, between
from locust_plugins.users.playwright import PlaywrightUser, pw, PageWithRetry, event

from opentelemetry import context, baggage, trace
from opentelemetry.context import Context
from opentelemetry.metrics import set_meter_provider
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.jinja2 import Jinja2Instrumentor
from opentelemetry.instrumentation.requests import RequestsInstrumentor
from opentelemetry.instrumentation.system_metrics import SystemMetricsInstrumentor
from opentelemetry.instrumentation.urllib3 import URLLib3Instrumentor
from opentelemetry.instrumentation.logging import LoggingInstrumentor
from opentelemetry._logs import set_logger_provider
from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.resources import Resource

from openfeature import api
from openfeature.contrib.provider.ofrep import OFREPProvider
from openfeature.contrib.hook.opentelemetry import TracingHook

from playwright.async_api import Route, Request

# Configure tracer provider first (needed for trace context in logs)
tracer_provider = TracerProvider()
trace.set_tracer_provider(tracer_provider)
tracer_provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(insecure=True)))

# Configure logger provider with the same resource
logger_provider = LoggerProvider()
set_logger_provider(logger_provider)

# Set up log exporter and processor
log_exporter = OTLPLogExporter(insecure=True)
logger_provider.add_log_record_processor(BatchLogRecordProcessor(log_exporter))

# Create logging handler that will include trace context
handler = LoggingHandler(level=logging.INFO, logger_provider=logger_provider)

# Configure root logger
root_logger = logging.getLogger()
root_logger.addHandler(handler)
root_logger.setLevel(logging.INFO)

# Configure metrics
metric_exporter = OTLPMetricExporter(insecure=True)
set_meter_provider(MeterProvider([PeriodicExportingMetricReader(metric_exporter)]))

# Instrument logging to automatically inject trace context
LoggingInstrumentor().instrument(set_logging_format=True)

# Instrumenting manually to avoid error with locust gevent monkey
Jinja2Instrumentor().instrument()
RequestsInstrumentor().instrument()
SystemMetricsInstrumentor().instrument()
URLLib3Instrumentor().instrument()

logging.info("Instrumentation complete - logs will now include trace context")

# Initialize Flagd provider
base_url = f"http://{os.environ.get('FLAGD_HOST', 'localhost')}:{os.environ.get('FLAGD_OFREP_PORT', 8016)}"
api.set_provider(OFREPProvider(base_url=base_url))
api.add_hooks([TracingHook()])

def get_flagd_value(FlagName):
    # Initialize OpenFeature
    client = api.get_client()
    return client.get_integer_value(FlagName, 0)


def get_recommendation_algorithm(user_id):
    """Evaluate the recommendationAlgorithm flag for a synthetic user,
    mirroring the same targeting logic used by the recommendation service."""
    import hashlib
    tier = "premium" if hashlib.sha256(user_id.encode()).digest()[-1] % 10 < 7 else "standard"
    client = api.get_client()
    from openfeature.evaluation_context import EvaluationContext
    ctx = EvaluationContext(targeting_key=user_id, attributes={"userTier": tier})
    return client.get_string_value("recommendationAlgorithm", "popularity", ctx)

categories = [
    "binoculars",
    "telescopes",
    "accessories",
    "assembly",
    "travel",
    "books",
    None,
]

products = [
    "0PUK6V6EV0",
    "1YMWWN1N4O",
    "2ZYFJ3GM2N",
    "66VCHSJNUP",
    "6E92ZMYYFZ",
    "9SIQT8TOJO",
    "L9ECAV7KIM",
    "LS4PSXUNUM",
    "OLJCESPC7Z",
    "HQTGWGPNH4",
]

people_file = open('people.json')
people = json.load(people_file)

browser_traffic_enabled = os.environ.get("LOCUST_BROWSER_TRAFFIC_ENABLED", "").lower() in ("true", "yes", "on")

if browser_traffic_enabled:
    class WebsiteBrowserUser(PlaywrightUser):
        headless = True  # to use a headless browser, without a GUI

        @task(3)
        @pw
        async def ask_ai_and_rate_summary(self, page: PageWithRetry):
            """Visits a product page, asks the AI for a review summary, then
            clicks 👍/👎 on the result. Drives the scenario-3 engagement
            signal (`summary_helpful_clicked` track event) so per-variant
            engagement rates land in the backend.

            If the AI never responds (e.g. `productSummaryModel=model-b`
            returned its simulated 500, or latency exceeded the wait), we
            skip the click — exactly the "user gave up" pattern that should
            depress model-b's engagement vs. model-a."""
            product = random.choice(products)
            tracer = trace.get_tracer(__name__)
            with tracer.start_as_current_span(
                "browser_ask_ai_and_rate_summary",
                context=Context(),
                attributes={"product.id": product},
            ):
                try:
                    page.on("console", lambda msg: print(msg.text))
                    await page.route('**/*', add_baggage_header)
                    await page.goto(f"/product/{product}", wait_until="domcontentloaded")

                    await page.click('[data-cy="QuickPromptSummarize"]')

                    import time as _time
                    started = _time.monotonic()
                    try:
                        await page.wait_for_selector('[data-cy="AIAnswer"]', timeout=10000)
                    except Exception:
                        logging.info(f"AI summary did not arrive in time for {product} — skipping helpful click")
                        return
                    elapsed_s = _time.monotonic() - started

                    # "Annoyed user" model: fast answers earn 👍, slow answers
                    # earn 👎. The mock LLM's `model-b` variant adds 0.5-1.5 s
                    # of latency per call (two calls per summarize round-trip
                    # ⇒ ~1.0-3.0 s total), so it lands above the 1.5 s
                    # threshold far more often than `model-a` does. Combined
                    # with the steep yes/no bias (0.90 vs 0.20), this produces
                    # an engagement-rate gap of roughly 0.85 vs 0.30 between
                    # variants.
                    slow_threshold_s = 1.5
                    prob_yes = 0.90 if elapsed_s < slow_threshold_s else 0.20

                    if random.random() < prob_yes:
                        await page.click('[data-cy="AIHelpfulYes"]')
                        logging.info(f"Clicked helpful=YES for {product} (elapsed={elapsed_s:.2f}s)")
                    else:
                        await page.click('[data-cy="AIHelpfulNo"]')
                        logging.info(f"Clicked helpful=NO  for {product} (elapsed={elapsed_s:.2f}s)")

                    await page.wait_for_timeout(2000)  # let the browser flush spans
                except Exception as e:
                    logging.error(f"Error in ask_ai_and_rate_summary task: {str(e)}")


async def add_baggage_header(route: Route, request: Request):
    existing_baggage = request.headers.get('baggage', '')
    headers = {
        **request.headers,
        'baggage': ', '.join(filter(None, (existing_baggage, 'synthetic_request=true')))
    }
    await route.continue_(headers=headers)
