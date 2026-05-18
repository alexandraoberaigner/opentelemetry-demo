#!/usr/bin/python

# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0


# Python
import hashlib
import math
import os
import random
import time
from concurrent import futures

# Pip

import grpc
from opentelemetry import trace, metrics, baggage as otel_baggage
from opentelemetry._logs import set_logger_provider
from opentelemetry.exporter.otlp.proto.grpc._log_exporter import (
    OTLPLogExporter,
)
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import SpanProcessor


class BaggageSpanProcessor(SpanProcessor):
    """Copies whitelisted OTel baggage entries onto every span as attributes.
    Lets us join flag-evaluation spans here with frontend tracking spans by
    `session.id` (set by the browser via SessionBaggagePropagator)."""

    def __init__(self, keys=("session.id",)):
        self._keys = tuple(keys)

    def on_start(self, span, parent_context=None):
        bag = otel_baggage.get_all(parent_context)
        for k in self._keys:
            v = bag.get(k)
            if v is not None:
                span.set_attribute(k, v)

    def on_end(self, span):
        pass

    def shutdown(self):
        pass

    def force_flush(self, timeout_millis=30000):
        return True

from openfeature import api
from openfeature.evaluation_context import EvaluationContext
from openfeature.contrib.provider.flagd import FlagdProvider

from openfeature.contrib.hook.opentelemetry import TracingHook

# Local
import logging
import demo_pb2
import demo_pb2_grpc
from grpc_health.v1 import health_pb2
from grpc_health.v1 import health_pb2_grpc

from metrics import (
    init_metrics
)

cached_ids = []
first_run = True

class RecommendationService(demo_pb2_grpc.RecommendationServiceServicer):
    def ListRecommendations(self, request, context):
        user_id = request.user_id or ""
        user_tier = derive_user_tier(user_id)
        algorithm = get_recommendation_algorithm(user_id)
        prod_list = get_product_list(request.product_ids, user_id)

        span = trace.get_current_span()
        span.set_attribute("app.products_recommended.count", len(prod_list))
        span.set_attribute("app.recommendation.algorithm", algorithm)
        span.set_attribute("app.user.tier", user_tier)
        span.set_attribute("app.user.id", user_id)
        logger.info(
            "recommendation served",
            extra={
                "app.user.id": user_id,
                "app.recommendation.algorithm": algorithm,
                "app.user.tier": user_tier,
            },
        )

        # build and return response
        response = demo_pb2.ListRecommendationsResponse()
        response.product_ids.extend(prod_list)

        # Collect metrics for this service
        rec_svc_metrics["app_recommendations_counter"].add(len(prod_list), {'recommendation.type': 'catalog'})
        rec_svc_metrics["app_recommendations_algorithm_counter"].add(
            len(prod_list),
            {'recommendation.algorithm': algorithm, 'user.tier': user_tier},
        )

        return response

    def Check(self, request, context):
        return health_pb2.HealthCheckResponse(
            status=health_pb2.HealthCheckResponse.SERVING)

    def Watch(self, request, context):
        return health_pb2.HealthCheckResponse(
            status=health_pb2.HealthCheckResponse.UNIMPLEMENTED)


def get_product_list(request_product_ids, user_id=""):
    global first_run
    global cached_ids
    with tracer.start_as_current_span("get_product_list") as span:
        max_responses = 5
        algorithm = get_recommendation_algorithm(user_id)
        span.set_attribute("app.recommendation.algorithm", algorithm)

        # Formulate the list of characters to list of strings
        request_product_ids_str = ''.join(request_product_ids)
        request_product_ids = request_product_ids_str.split(',')

        # Feature flag scenario - Cache Leak
        if check_feature_flag("recommendationCacheFailure"):
            span.set_attribute("app.recommendation.cache_enabled", True)
            if random.random() < 0.5 or first_run:
                first_run = False
                span.set_attribute("app.cache_hit", False)
                logger.info("get_product_list: cache miss")
                cat_response = product_catalog_stub.ListProducts(demo_pb2.Empty())
                response_ids = [x.id for x in cat_response.products]
                cached_ids = cached_ids + response_ids
                cached_ids = cached_ids + cached_ids[:len(cached_ids) // 4]
                product_ids = cached_ids
            else:
                span.set_attribute("app.cache_hit", True)
                logger.info("get_product_list: cache hit")
                product_ids = cached_ids
        else:
            span.set_attribute("app.recommendation.cache_enabled", False)
            cat_response = product_catalog_stub.ListProducts(demo_pb2.Empty())
            product_ids = [x.id for x in cat_response.products]

        span.set_attribute("app.products.count", len(product_ids))

        # Create a filtered list of products excluding the products received as input
        filtered_products = list(set(product_ids) - set(request_product_ids))
        num_products = len(filtered_products)
        span.set_attribute("app.filtered_products.count", num_products)
        num_return = min(max_responses, num_products)

        # Selection strategy driven by the recommendationAlgorithm flag.
        # The OpenFeature OTel TracingHook attaches feature_flag.* SemConv
        # attributes to the active span automatically — no extra code needed.
        if algorithm == "popularity":
            prod_list = filtered_products[:num_return]
        elif algorithm == "collaborative":
            sorted_products = sorted(filtered_products)
            prod_list = sorted_products[:num_return]
        elif algorithm == "personalized":
            seed = sum(ord(c) for c in (request_product_ids_str or "anon"))
            rng = random.Random(seed)
            prod_list = rng.sample(filtered_products, num_return)
            # Simulate inference latency for the heavier personalized model.
            # Log-normal distribution: median ~120ms, p95 ~250ms — realistic
            # inference tail without being alarming.
            latency = random.lognormvariate(mu=math.log(0.12), sigma=0.35)
            latency = max(0.04, min(latency, 1.0))  # clamp 40ms–1s
            time.sleep(latency)
        else:
            indices = random.sample(range(num_products), num_return)
            prod_list = [filtered_products[i] for i in indices]

        span.set_attribute("app.filtered_products.list", prod_list)

        return prod_list


def must_map_env(key: str):
    value = os.environ.get(key)
    if value is None:
        raise Exception(f'{key} environment variable must be set')
    return value


def derive_user_tier(user_id: str) -> str:
    """Deterministically derive a user tier from the user ID.

    ~70% of user IDs are mapped to 'premium' (last byte % 10 < 7).
    """
    if not user_id:
        return "standard"
    digest = hashlib.sha256(user_id.encode()).digest()
    return "premium" if digest[-1] % 10 < 7 else "standard"


def check_feature_flag(flag_name: str):
    # Initialize OpenFeature
    client = api.get_client()
    return client.get_boolean_value("recommendationCacheFailure", False)


def get_recommendation_algorithm(user_id: str = "") -> str:
    client = api.get_client()
    user_tier = derive_user_tier(user_id)
    ctx = EvaluationContext(
        targeting_key=user_id or None,
        attributes={"userTier": user_tier},
    )
    return client.get_string_value("recommendationAlgorithm", "popularity", ctx)


if __name__ == "__main__":
    service_name = must_map_env('OTEL_SERVICE_NAME')
    api.set_provider(FlagdProvider(host=os.environ.get('FLAGD_HOST', 'flagd'), port=os.environ.get('FLAGD_PORT', 8013)))
    api.add_hooks([TracingHook()])

    # Initialize Traces and Metrics
    tracer = trace.get_tracer_provider().get_tracer(service_name)
    meter = metrics.get_meter_provider().get_meter(service_name)
    rec_svc_metrics = init_metrics(meter)

    # Copy session.id from incoming OTel baggage onto every span.
    trace.get_tracer_provider().add_span_processor(BaggageSpanProcessor())

    # Initialize Logs
    logger_provider = LoggerProvider(
        resource=Resource.create(
            {
                'service.name': service_name,
            }
        ),
    )
    set_logger_provider(logger_provider)
    log_exporter = OTLPLogExporter(insecure=True)
    logger_provider.add_log_record_processor(BatchLogRecordProcessor(log_exporter))
    handler = LoggingHandler(level=logging.NOTSET, logger_provider=logger_provider)

    # Attach OTLP handler to logger
    logger = logging.getLogger('main')
    logger.addHandler(handler)

    catalog_addr = must_map_env('PRODUCT_CATALOG_ADDR')
    pc_channel = grpc.insecure_channel(catalog_addr)
    product_catalog_stub = demo_pb2_grpc.ProductCatalogServiceStub(pc_channel)

    # Create gRPC server
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))

    # Add class to gRPC server
    service = RecommendationService()
    demo_pb2_grpc.add_RecommendationServiceServicer_to_server(service, server)
    health_pb2_grpc.add_HealthServicer_to_server(service, server)

    # Start server
    port = must_map_env('RECOMMENDATION_PORT')
    server.add_insecure_port(f'[::]:{port}')
    server.start()
    logger.info(f'Recommendation service started, listening on port {port}')
    server.wait_for_termination()
