"""
Sprint 3 – BLOQUE 4: Request Context Middleware
Adds X-Request-ID header to all requests for distributed tracing.
Logs structured request info (method, path, status, latency).
"""
import time
from uuid import uuid4

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from src.utils.logging_config import set_trace_id, logger


class RequestContextMiddleware(BaseHTTPMiddleware):
    """
    Middleware that:
    1. Reads or generates X-Request-ID
    2. Sets it in the ContextVar for log correlation
    3. Adds it to the response headers
    4. Logs structured request info with latency
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        # Read or generate request ID
        request_id = request.headers.get("X-Request-ID") or str(uuid4())
        request.state.request_id = request_id

        # Set trace ID for log correlation
        set_trace_id(request_id)

        start = time.time()
        response = await call_next(request)
        latency_ms = (time.time() - start) * 1000

        # Add request ID to response headers
        response.headers["X-Request-ID"] = request_id

        # Log structured request info (skip health/metrics for noise reduction)
        path = request.url.path
        if not path.startswith(("/api/health", "/metrics")):
            logger.bind(trace_id=request_id).info(
                "HTTP_REQUEST | method={} | path={} | status={} | latency_ms={:.2f}",
                request.method, path, response.status_code, latency_ms,
            )

        return response
