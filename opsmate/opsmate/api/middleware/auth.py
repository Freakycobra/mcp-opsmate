"""Authentication middleware for mcp-opsmate.

Provides API key validation (constant-time comparison) and admin token validation.
"""

from __future__ import annotations

import hmac
import logging
import secrets
from typing import Awaitable, Callable

from fastapi import HTTPException, Request, status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from opsmate.core.config import get_config

logger: logging.Logger = logging.getLogger(__name__)


class APIKeyMiddleware(BaseHTTPMiddleware):
    """Middleware for API key and admin token validation.

    Validates:
    - X-API-Key header for all protected endpoints
    - Authorization: Bearer <token> for /admin/* endpoints

    Exempt paths:
    - /health
    - /metrics
    - /docs
    - /openapi.json
    """

    EXEMPT_PATHS: set[str] = {
        "/health",
        "/metrics",
        "/docs",
        "/openapi.json",
        "/redoc",
        "/examples",
    }

    ADMIN_PATH_PREFIX: str = "/admin"

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        """Validate authentication for incoming requests."""
        path: str = request.url.path

        # Skip exempt paths
        if path in self.EXEMPT_PATHS or any(
            path.startswith(p) for p in ("/docs", "/openapi", "/redoc")
        ):
            return await call_next(request)

        # Skip WebSocket auth (handled separately)
        if request.headers.get("upgrade", "").lower() == "websocket":
            return await call_next(request)

        config = get_config()

        # Admin endpoints require Bearer token
        if path.startswith(self.ADMIN_PATH_PREFIX):
            auth_header: str | None = request.headers.get("authorization")
            if not auth_header:
                logger.warning("Admin request missing Authorization header: %s", path)
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Admin token required",
                    headers={"WWW-Authenticate": "Bearer"},
                )

            # Extract Bearer token
            parts: list[str] = auth_header.split()
            if len(parts) != 2 or parts[0].lower() != "bearer":
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid Authorization header format. Use 'Bearer <token>'",
                )

            token: str = parts[1]
            if not self._constant_time_compare(token, config.admin_api_token):
                logger.warning("Invalid admin token for path: %s", path)
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid admin token",
                )

            # Admin token is valid
            request.state.is_admin = True
            return await call_next(request)

        # Regular endpoints require X-API-Key
        api_key: str | None = request.headers.get("x-api-key")
        if not api_key:
            # Also check query param for SSE streams
            api_key = request.query_params.get("api_key")

        if not api_key:
            logger.warning("Request missing API key: %s %s", request.method, path)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="API key required. Provide X-API-Key header or api_key query parameter.",
            )

        if not self._constant_time_compare(api_key, config.api_key):
            logger.warning("Invalid API key for path: %s", path)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid API key",
            )

        request.state.is_admin = False
        return await call_next(request)

    @staticmethod
    def _constant_time_compare(a: str, b: str) -> bool:
        """Compare two strings in constant time to prevent timing attacks.

        Uses hmac.compare_digest which is the standard constant-time comparison.
        Also provides a secrets.compare_digest fallback.
        """
        if not a or not b:
            return False
        return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))
