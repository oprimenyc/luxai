"""Orchestrator observability — OpenTelemetry + LangSmith + structlog."""

import os
from functools import wraps
from time import perf_counter
from typing import Any, Callable, TypeVar

import structlog
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

from src.config import settings

log = structlog.get_logger(__name__)
F = TypeVar("F", bound=Callable[..., Any])


def configure_telemetry() -> TracerProvider:
    """Set up tracing for the orchestrator service."""
    if settings.langchain_tracing_v2 and settings.langchain_api_key:
        os.environ["LANGCHAIN_API_KEY"] = settings.langchain_api_key
        os.environ["LANGCHAIN_TRACING_V2"] = "true"
        os.environ["LANGCHAIN_PROJECT"] = settings.langchain_project
        os.environ["LANGCHAIN_ENDPOINT"] = settings.langchain_endpoint
        log.info("langsmith_tracing_enabled", project=settings.langchain_project)

    resource = Resource.create({
        "service.name": "luxai-orchestrator",
        "service.version": settings.app_version,
        "deployment.environment": settings.environment,
    })
    provider = TracerProvider(resource=resource)

    if settings.environment == "development":
        import sys
        provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter(out=sys.stderr)))

    trace.set_tracer_provider(provider)
    log.info("telemetry_configured", environment=settings.environment)
    return provider


def traced(operation_name: str | None = None) -> Callable[[F], F]:
    """Decorator — wraps an async function in an OTel span."""
    def decorator(func: F) -> F:
        name = operation_name or f"{func.__module__}.{func.__qualname__}"
        tracer = trace.get_tracer(__name__)

        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            start = perf_counter()
            with tracer.start_as_current_span(name) as span:
                try:
                    result = await func(*args, **kwargs)
                    span.set_attribute("duration_ms", round((perf_counter() - start) * 1000, 2))
                    return result
                except Exception as exc:
                    span.record_exception(exc)
                    span.set_status(trace.StatusCode.ERROR, str(exc))
                    log.error(f"{name}_failed", error=str(exc))
                    raise

        return wrapper  # type: ignore[return-value]
    return decorator


def record_token_usage(
    model: str,
    input_tokens: int,
    output_tokens: int,
    session_id: str | None = None,
) -> None:
    span = trace.get_current_span()
    span.set_attribute("llm.model", model)
    span.set_attribute("llm.input_tokens", input_tokens)
    span.set_attribute("llm.output_tokens", output_tokens)
    if session_id:
        span.set_attribute("session.id", session_id)

    log.info(
        "token_usage",
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        session_id=session_id,
    )
