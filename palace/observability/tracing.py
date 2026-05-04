"""OpenTelemetry setup. Optional — enabled iff settings.otlp_endpoint is set
and the optional ``otel`` extra is installed.

This module imports the OTel SDK lazily so that the base server install
(without the ``otel`` extra) doesn't drag heavy tracing deps into the wheel.
"""

from __future__ import annotations

import logging

from palace.config import settings

logger = logging.getLogger(__name__)

_initialized = False


def configure_tracing(app=None) -> bool:
    """Wire OpenTelemetry. Returns True iff tracing is now active.

    No-op if ``settings.otlp_endpoint`` is unset, or if the otel SDK isn't
    installed (gives a one-time INFO log so operators know to install
    palace-memory[otel] if they want traces).
    """
    global _initialized
    if _initialized:
        return True
    if settings.otlp_endpoint is None:
        return False

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError:
        logger.info(
            "PALACE_OTLP_ENDPOINT set but opentelemetry SDK not installed; "
            "install palace-memory[otel] to enable traces.",
        )
        return False

    resource = Resource.create({"service.name": settings.otlp_service_name})
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=settings.otlp_endpoint)),
    )
    trace.set_tracer_provider(provider)

    # Auto-instrument FastAPI + httpx if present. Each instrumentor is opt-in.
    if app is not None:
        try:
            from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
            FastAPIInstrumentor.instrument_app(app)
        except ImportError:
            pass

    try:
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
        HTTPXClientInstrumentor().instrument()
    except ImportError:
        pass

    _initialized = True
    logger.info(
        "OpenTelemetry tracing active (endpoint=%s, service=%s)",
        settings.otlp_endpoint, settings.otlp_service_name,
    )
    return True
