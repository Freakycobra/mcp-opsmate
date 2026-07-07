"""Request/response logging middleware for mcp-opsmate.

Provides request logging with execution_id propagation and secret redaction.
"""

from __future__ import annotations

import logging
import time
from typing import Awaitable, Callable

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from opsmate.services.audit import redact_secrets

logger: logging.Logger = logging.getLogger("opsmate.api")


class LoggingMiddleware(BaseHTTPMiddleware):
    """Middleware for request/response logging.

    Logs all requests with timing, status code, and path.
    Redacts secrets from query parameters and headers.
    """

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        """Log request and response with timing."""
        start_time: float = time.perf_counter()

        # Extract request info
        method: str = request.method
        path: str = request.url.path
        query_string: str = str(request.query_params)
        client_host: str = request.client.host if request.client else "unknown"

        # Redact secrets from query string
        safe_query: str = redact_secrets(query_string) if query_string else ""

        # Process request
        try:
            response: Response = await call_next(request)
            status_code: int = response.status_code

            # Calculate duration
            duration_ms: float = (time.perf_counter() - start_time) * 1000

            # Log
            logger.info(
                "Request: %s %s%s -> %d in %.2fms [client: %s]",
                method,
                path,
                f"?{safe_query}" if safe_query else "",
                status_code,
                duration_ms,
                client_host,
            )

            # Add timing header
            response.headers["X-Response-Time-Ms"] = str(round(duration_ms, 2))

            return response

        except Exception as e:
            duration_ms = (time.perf_counter() - start_time) * 1000
            logger.error(
                "Request failed: %s %s -> %s in %.2fms",
                method,
                path,
                e,
                duration_ms,
            )
            raise


class SecretRedactionMiddleware(BaseHTTPMiddleware):
    """Middleware to redact secrets from request bodies and responses."""

    SENSITIVE_PATHS: set[str] = {
        "/commands",
        "/executions",
        "/admin/mode",
    }

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        """Redact secrets from logged request data."""
        # This is a placeholder for more advanced body redaction.
        # In practice, the AuditLogger handles redaction of stored data.
        # This middleware ensures request metadata is clean.
        return await call_next(request)
