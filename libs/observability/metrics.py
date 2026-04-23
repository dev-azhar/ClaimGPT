"""
Prometheus metrics middleware for FastAPI.

Exposes /metrics endpoint and tracks request latency, count, and errors.
"""

from __future__ import annotations

import logging
import os
import time

logger = logging.getLogger("observability.metrics")

_METRICS_ENABLED = os.getenv("METRICS_ENABLED", "false").lower() == "true"

# Lazy-init Prometheus objects
_REQUEST_DURATION = None
_REQUEST_COUNT = None
_REQUEST_ERRORS = None


def init_metrics(service_name: str) -> None:
    """Set up Prometheus metrics collectors."""
    global _REQUEST_DURATION, _REQUEST_COUNT, _REQUEST_ERRORS

    if not _METRICS_ENABLED:
        logger.info("Prometheus metrics disabled (set METRICS_ENABLED=true to enable)")
        return

    try:
        from prometheus_client import Counter, Histogram

        _REQUEST_DURATION = Histogram(
            "http_request_duration_seconds",
            "HTTP request duration in seconds",
            ["method", "path", "status"],
        )
        _REQUEST_COUNT = Counter(
            "http_requests_total",
            "Total HTTP requests",
            ["method", "path", "status"],
        )
        _REQUEST_ERRORS = Counter(
            "http_request_errors_total",
            "Total HTTP request errors (5xx)",
            ["method", "path"],
        )
        logger.info("Prometheus metrics initialized for '%s'", service_name)
    except ImportError:
        logger.warning("prometheus_client not installed — metrics disabled")


class PrometheusMiddleware:
    """ASGI middleware that records request metrics."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not _METRICS_ENABLED:
            return await self.app(scope, receive, send)

        path = scope.get("path", "")
        method = scope.get("method", "GET")

        # Skip metrics endpoint itself
        if path == "/metrics":
            return await self.app(scope, receive, send)

        start = time.monotonic()
        status_code = 500  # default in case of unhandled error

        async def _send_wrapper(message):
            nonlocal status_code
            if message.get("type") == "http.response.start":
                status_code = message.get("status", 500)
            await send(message)

        try:
            await self.app(scope, receive, _send_wrapper)
        finally:
            duration = time.monotonic() - start
            status_str = str(status_code)

            if _REQUEST_DURATION is not None:
                _REQUEST_DURATION.labels(method=method, path=path, status=status_str).observe(duration)
            if _REQUEST_COUNT is not None:
                _REQUEST_COUNT.labels(method=method, path=path, status=status_str).inc()
            if _REQUEST_ERRORS is not None and status_code >= 500:
                _REQUEST_ERRORS.labels(method=method, path=path).inc()


def metrics_endpoint():
    """Return a FastAPI route handler for /metrics."""
    try:
        from fastapi.responses import Response
        from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

        def _metrics():
            return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
        return _metrics
    except ImportError:
        from fastapi.responses import JSONResponse

        def _metrics():
            return JSONResponse({"error": "prometheus_client not installed"}, status_code=501)
        return _metrics
