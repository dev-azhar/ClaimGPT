"""
OpenTelemetry distributed tracing setup.

Call `init_tracing(service_name)` at application startup to enable tracing.
Traces are exported to an OTLP-compatible collector (Jaeger, Tempo, etc.).
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger("observability.tracing")

_OTLP_ENDPOINT = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")
_OTEL_ENABLED = os.getenv("OTEL_ENABLED", "false").lower() == "true"


def init_tracing(service_name: str) -> None:
    """
    Initialize OpenTelemetry tracing with OTLP exporter.

    Requires:
      - opentelemetry-api
      - opentelemetry-sdk
      - opentelemetry-exporter-otlp-proto-grpc
      - opentelemetry-instrumentation-fastapi
      - opentelemetry-instrumentation-sqlalchemy
    """
    if not _OTEL_ENABLED:
        logger.info("OpenTelemetry tracing disabled (set OTEL_ENABLED=true to enable)")
        return

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        resource = Resource.create({"service.name": service_name})
        provider = TracerProvider(resource=resource)

        exporter = OTLPSpanExporter(endpoint=_OTLP_ENDPOINT)
        provider.add_span_processor(BatchSpanProcessor(exporter))

        trace.set_tracer_provider(provider)
        logger.info("OpenTelemetry tracing initialized for '%s' → %s", service_name, _OTLP_ENDPOINT)

    except ImportError:
        logger.warning("OpenTelemetry packages not installed — tracing disabled")


def instrument_fastapi(app, service_name: str = "") -> None:
    """Instrument a FastAPI app with OpenTelemetry."""
    if not _OTEL_ENABLED:
        return
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        FastAPIInstrumentor.instrument_app(app)
        logger.info("FastAPI instrumented for tracing")
    except ImportError:
        pass


def instrument_sqlalchemy(engine) -> None:
    """Instrument a SQLAlchemy engine with OpenTelemetry."""
    if not _OTEL_ENABLED:
        return
    try:
        from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
        SQLAlchemyInstrumentor().instrument(engine=engine)
        logger.info("SQLAlchemy instrumented for tracing")
    except ImportError:
        pass
