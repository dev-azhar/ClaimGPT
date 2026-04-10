"""Observability: OpenTelemetry tracing + Prometheus metrics for FastAPI services."""

from .metrics import PrometheusMiddleware, init_metrics
from .tracing import init_tracing

__all__ = ["init_tracing", "init_metrics", "PrometheusMiddleware"]
