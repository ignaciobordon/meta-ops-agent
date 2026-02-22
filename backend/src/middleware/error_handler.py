"""
Sprint 3 – BLOQUE 8: Global Error Handler
Unified JSON error responses. No stack traces leaked to client.
"""
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from src.utils.logging_config import logger, get_trace_id


class GlobalErrorHandler(BaseHTTPMiddleware):
    """
    Catches unhandled exceptions and returns a structured JSON error.
    Must be outermost middleware (added last in add_middleware chain).
    """

    async def dispatch(self, request: Request, call_next):
        try:
            response = await call_next(request)
            return response
        except Exception as exc:
            request_id = getattr(request.state, "request_id", get_trace_id())
            logger.bind(trace_id=request_id).error(
                "UNHANDLED_ERROR | path={} | error={}",
                request.url.path, str(exc),
            )
            return JSONResponse(
                status_code=500,
                content={
                    "error": {
                        "code": "INTERNAL_ERROR",
                        "message": "An unexpected error occurred",
                        "request_id": request_id,
                    }
                },
            )
