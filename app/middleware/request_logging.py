"""Request logging middleware."""

from __future__ import annotations

import time

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.core.logging import get_logger

logger = get_logger("middleware.request")


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Log method, path, status code, and duration for each HTTP request."""

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            duration_ms = (time.perf_counter() - start) * 1000
            logger.exception(
                "Request failed | %s %s | %.2fms",
                request.method,
                request.url.path,
                duration_ms,
            )
            raise

        duration_ms = (time.perf_counter() - start) * 1000
        logger.info(
            "%s %s -> %s | %.2fms",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
        )
        return response
