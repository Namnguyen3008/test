"""PHI-safe tracing, metrics and structured request telemetry."""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Mapping
from typing import Any

from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from prometheus_client import Counter, Histogram, make_asgi_app
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from src.config import Settings

logger = logging.getLogger("vmec.request")
REQUESTS = Counter(
    "vmec_http_requests_total",
    "HTTP requests by method, route template and status.",
    ("method", "route", "status"),
)
LATENCY = Histogram(
    "vmec_http_request_duration_seconds",
    "HTTP request duration by method and route template.",
    ("method", "route"),
)


def _route_template(scope: Scope) -> str:
    route = scope.get("route")
    path = getattr(route, "path", None)
    if not path:
        return "unmatched"
    raw_path = str(scope.get("path", ""))
    static_prefix = str(path).split("{", maxsplit=1)[0].rstrip("/")
    position = raw_path.rfind(static_prefix) if static_prefix else -1
    return f"{raw_path[:position]}{path}" if position >= 0 else str(path)


class SafeRequestTelemetryMiddleware:
    """Record only aggregate request metadata; never body, query, headers or identity."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = time.monotonic()
        status = 500

        async def capture_status(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = int(message["status"])
            await send(message)

        try:
            await self.app(scope, receive, capture_status)
        finally:
            route = _route_template(scope)
            method = str(scope.get("method", "UNKNOWN"))
            duration = time.monotonic() - started
            REQUESTS.labels(method=method, route=route, status=str(status)).inc()
            LATENCY.labels(method=method, route=route).observe(duration)
            span_context = trace.get_current_span().get_span_context()
            trace_id = f"{span_context.trace_id:032x}" if span_context.is_valid else ""
            event: Mapping[str, object] = {
                "event": "http_request",
                "method": method,
                "route": route,
                "status": status,
                "latency_ms": round(duration * 1000),
                "trace_id": trace_id,
            }
            logger.info(json.dumps(event, sort_keys=True, separators=(",", ":")))


def _sanitize_server_span(span: Any, scope: dict[str, Any]) -> None:
    """Overwrite URL attributes so query strings and concrete identifiers are not exported."""
    if span and span.is_recording():
        path = str(scope.get("path", ""))
        span.set_attribute("url.full", path)
        span.set_attribute("url.query", "")
        span.set_attribute("http.target", path)


def configure_observability(app: FastAPI, settings: Settings) -> None:
    provider = TracerProvider(resource=Resource.create({"service.name": settings.otel_service_name}))
    if settings.otel_exporter_otlp_traces_endpoint:
        exporter = OTLPSpanExporter(endpoint=settings.otel_exporter_otlp_traces_endpoint)
        provider.add_span_processor(BatchSpanProcessor(exporter))
    FastAPIInstrumentor.instrument_app(
        app,
        tracer_provider=provider,
        excluded_urls="health,ready,metrics",
        server_request_hook=_sanitize_server_span,
        http_capture_headers_server_request=[],
        http_capture_headers_server_response=[],
        exclude_spans=["receive", "send"],
    )
    app.add_middleware(SafeRequestTelemetryMiddleware)
    app.mount("/metrics", make_asgi_app())
