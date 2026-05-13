"""Tracing middleware — request correlation and span injection."""

from collections.abc import Callable
from time import perf_counter

import structlog
from fastapi import Request, Response
from opentelemetry import trace
from starlette.middleware.base import BaseHTTPMiddleware

log = structlog.get_logger(__name__)
tracer = trace.get_tracer("luxai.api.middleware")


class TracingMiddleware(BaseHTTPMiddleware):
    """Inject trace context into structlog and enrich spans."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:  # type: ignore[override]
        with tracer.start_as_current_span(
            f"{request.method} {request.url.path}",
            kind=trace.SpanKind.SERVER,
        ) as span:
            span.set_attribute("http.method", request.method)
            span.set_attribute("http.url", str(request.url))
            span.set_attribute("http.path", request.url.path)

            request_id = request.headers.get("X-Request-ID", "")
            if request_id:
                span.set_attribute("request.id", request_id)

            start = perf_counter()
            structlog.contextvars.bind_contextvars(
                trace_id=format(span.get_span_context().trace_id, "032x"),
                request_id=request_id,
            )

            try:
                response = await call_next(request)
                duration_ms = round((perf_counter() - start) * 1000, 2)
                span.set_attribute("http.status_code", response.status_code)
                span.set_attribute("http.duration_ms", duration_ms)
                return response
            except Exception as exc:
                span.record_exception(exc)
                span.set_status(trace.StatusCode.ERROR, str(exc))
                raise
            finally:
                structlog.contextvars.clear_contextvars()
