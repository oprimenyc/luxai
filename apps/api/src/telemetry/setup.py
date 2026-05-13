"""OpenTelemetry + structlog + Prometheus configuration."""

import logging
import os
import sys

import structlog
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased


def configure_logging(environment: str = "development") -> None:
    """Configure structlog with JSON output in production."""
    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
    ]

    if environment == "production":
        processors = shared_processors + [
            structlog.processors.dict_tracebacks,
            structlog.processors.JSONRenderer(),
        ]
        renderer = structlog.processors.JSONRenderer()
    else:
        processors = shared_processors + [
            structlog.dev.ConsoleRenderer(colors=True),
        ]
        renderer = structlog.dev.ConsoleRenderer(colors=True)

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(logging.DEBUG),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def configure_tracing(
    service_name: str = "luxai-api",
    environment: str = "development",
    otlp_endpoint: str | None = None,
    sample_rate: float = 1.0,
) -> TracerProvider:
    """Configure OpenTelemetry tracing."""
    resource = Resource.create({
        "service.name": service_name,
        "service.version": os.getenv("APP_VERSION", "0.1.0"),
        "deployment.environment": environment,
    })

    sampler = ParentBased(
        root=TraceIdRatioBased(sample_rate),
    )

    provider = TracerProvider(resource=resource, sampler=sampler)

    if otlp_endpoint:
        otlp_exporter = OTLPSpanExporter(endpoint=otlp_endpoint, insecure=True)
        provider.add_span_processor(BatchSpanProcessor(otlp_exporter))
    elif environment == "development":
        provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter(out=sys.stderr)))

    trace.set_tracer_provider(provider)
    return provider


def instrument_app(app: object) -> None:
    """Auto-instrument FastAPI + httpx."""
    FastAPIInstrumentor.instrument_app(app)  # type: ignore[arg-type]
    HTTPXClientInstrumentor().instrument()


def get_tracer(name: str) -> trace.Tracer:
    return trace.get_tracer(name)
