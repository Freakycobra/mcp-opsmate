"""HTTP client for the FastAPI backend.

Provides:
- REST API methods for command submission, execution queries, plan approval
- SSE streaming consumer for real-time execution updates
- Configurable base URL, timeout, and authentication
"""

from __future__ import annotations

import json
from typing import Any, AsyncGenerator
from uuid import UUID

import httpx
from httpx_sse import aconnect_sse

from opsmate_cli.config import get_config
from opsmate_cli.models import (
    ClarificationResponse,
    CommandRequest,
    CommandResponse,
    ErrorResponse,
    ExamplesResponse,
    ExecutionDetailResponse,
    ExecutionListResponse,
    HealthResponse,
    PlanApprovalRequest,
    PlanApprovalResponse,
)


class APIError(Exception):
    """Base exception for API client errors."""

    def __init__(self, message: str, status_code: int | None = None, response_body: dict[str, Any] | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body or {}


class AuthenticationError(APIError):
    """Raised when API authentication fails."""

    pass


class ValidationError(APIError):
    """Raised when request validation fails."""

    pass


class ServerUnavailableError(APIError):
    """Raised when the backend server is unavailable."""

    pass


class ClarificationRequiredError(APIError):
    """Raised when the command needs clarification (422 response)."""

    def __init__(self, clarification: ClarificationResponse):
        super().__init__(clarification.reason, status_code=422)
        self.clarification = clarification


class APIClient:
    """Async HTTP client for the OpsMate FastAPI backend.

    Usage:
        async with APIClient() as client:
            resp = await client.submit_command("check health of payment-service")
            async for event in client.stream_events(resp.execution_id):
                print(event)
    """

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        timeout: float | None = None,
        sse_timeout: float | None = None,
    ) -> None:
        """Initialize the API client.

        Args:
            base_url: Backend base URL. Defaults to config api_url.
            api_key: API key for authentication. Defaults to config api_key.
            timeout: HTTP request timeout. Defaults to config timeout.
            sse_timeout: SSE stream timeout. Defaults to config sse_timeout.
        """
        config = get_config()
        self.base_url = (base_url or config.api_url).rstrip("/")
        self.api_key = api_key or config.api_key
        self.timeout = timeout or config.timeout
        self.sse_timeout = sse_timeout or config.sse_timeout

        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(self.timeout, connect=10.0),
            headers=self._build_headers(),
            follow_redirects=True,
        )

    def _build_headers(self) -> dict[str, str]:
        """Build default HTTP headers with auth if configured."""
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "opsmate-cli/0.1.0",
        }
        if self.api_key:
            headers["X-API-Key"] = self.api_key
        return headers

    async def __aenter__(self) -> "APIClient":
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()

    # ── HTTP Response Handling ────────────────────────────────────────────────

    @staticmethod
    def _handle_error(response: httpx.Response) -> None:
        """Raise appropriate exception for non-2xx responses.

        Args:
            response: HTTP response to check.

        Raises:
            AuthenticationError: For 401 responses.
            ValidationError: For 400/422 responses.
            ServerUnavailableError: For 503 responses.
            APIError: For other non-2xx responses.
        """
        if response.status_code < 300:
            return

        try:
            body = response.json()
        except (json.JSONDecodeError, httpx.DecodingError):
            body = {"error": response.text or "Unknown error"}

        error_msg = body.get("error", body.get("detail", "Unknown error"))

        if response.status_code == 401:
            raise AuthenticationError(f"Authentication failed: {error_msg}", status_code=401, response_body=body)
        elif response.status_code == 403:
            raise AuthenticationError(f"Permission denied: {error_msg}", status_code=403, response_body=body)
        elif response.status_code == 422:
            # Check if this is a clarification response
            if "confidence" in body and "suggested_rephrasings" in body:
                clarification = ClarificationResponse.model_validate(body)
                raise ClarificationRequiredError(clarification)
            raise ValidationError(f"Validation error: {error_msg}", status_code=422, response_body=body)
        elif response.status_code == 400:
            raise ValidationError(f"Bad request: {error_msg}", status_code=400, response_body=body)
        elif response.status_code == 404:
            raise APIError(f"Not found: {error_msg}", status_code=404, response_body=body)
        elif response.status_code == 409:
            raise APIError(f"Conflict: {error_msg}", status_code=409, response_body=body)
        elif response.status_code == 503:
            raise ServerUnavailableError(f"Server unavailable: {error_msg}", status_code=503, response_body=body)
        else:
            raise APIError(f"HTTP {response.status_code}: {error_msg}", status_code=response.status_code, response_body=body)

    # ── API Methods ───────────────────────────────────────────────────────────

    async def submit_command(
        self,
        text: str,
        auto_approve: bool = False,
        execution_mode_override: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> CommandResponse:
        """Submit a natural language command for execution.

        Args:
            text: Natural language command text.
            auto_approve: Skip plan confirmation for single-step plans.
            execution_mode_override: Override execution mode (mock/live/mixed).
            metadata: Optional client metadata.

        Returns:
            CommandResponse with execution_id and stream_url.

        Raises:
            AuthenticationError: If API key is invalid.
            ValidationError: If command is empty or too long.
            ClarificationRequiredError: If intent confidence is too low.
            ServerUnavailableError: If backend is down.
        """
        request = CommandRequest(
            text=text,
            auto_approve=auto_approve,
            metadata=metadata or {},
            execution_mode_override=execution_mode_override,  # type: ignore[arg-type]
        )

        response = await self._client.post(
            "/commands",
            content=request.model_dump_json(),
        )
        self._handle_error(response)
        return CommandResponse.model_validate(response.json())

    async def get_execution(self, execution_id: UUID | str) -> ExecutionDetailResponse:
        """Get full execution details.

        Args:
            execution_id: Execution UUID.

        Returns:
            ExecutionDetailResponse with full state.

        Raises:
            AuthenticationError: If API key is invalid.
            APIError: If execution not found.
        """
        response = await self._client.get(f"/executions/{execution_id}")
        self._handle_error(response)
        return ExecutionDetailResponse.model_validate(response.json())

    async def list_executions(
        self,
        page: int = 1,
        page_size: int = 20,
        status: str | None = None,
        mode: str | None = None,
        command_q: str | None = None,
        sort: str = "-created_at",
    ) -> ExecutionListResponse:
        """List execution history with pagination and filtering.

        Args:
            page: Page number (1-indexed).
            page_size: Items per page (max 100).
            status: Filter by execution status.
            mode: Filter by execution mode.
            command_q: Fuzzy search on command text.
            sort: Sort field, prefix - for descending.

        Returns:
            ExecutionListResponse with paginated results.
        """
        params: dict[str, Any] = {
            "page": page,
            "page_size": min(page_size, 100),
            "sort": sort,
        }
        if status:
            params["status"] = status
        if mode:
            params["mode"] = mode
        if command_q:
            params["command_q"] = command_q

        response = await self._client.get("/executions", params=params)
        self._handle_error(response)
        return ExecutionListResponse.model_validate(response.json())

    async def approve_plan(
        self,
        execution_id: UUID | str,
        decision: str = "approve",
        reason: str | None = None,
    ) -> PlanApprovalResponse:
        """Approve, reject, or modify a pending execution plan.

        Args:
            execution_id: Execution UUID.
            decision: One of "approve", "reject", "modify".
            reason: Optional reason for rejection/modification.

        Returns:
            PlanApprovalResponse with updated status.

        Raises:
            AuthenticationError: If API key is invalid.
            APIError: If execution not found or not awaiting confirmation.
        """
        request = PlanApprovalRequest(decision=decision, reason=reason)  # type: ignore[arg-type]

        response = await self._client.post(
            f"/executions/{execution_id}/approve",
            content=request.model_dump_json(),
        )
        self._handle_error(response)
        return PlanApprovalResponse.model_validate(response.json())

    async def get_examples(self) -> ExamplesResponse:
        """Get built-in demo commands.

        Returns:
            ExamplesResponse with list of demo commands.
        """
        response = await self._client.get("/examples")
        self._handle_error(response)
        return ExamplesResponse.model_validate(response.json())

    async def health_check(self) -> HealthResponse:
        """Check backend health.

        Returns:
            HealthResponse with status and check details.

        Raises:
            APIError: If backend is unhealthy.
        """
        try:
            response = await self._client.get("/health")
            self._handle_error(response)
            return HealthResponse.model_validate(response.json())
        except httpx.ConnectError as e:
            raise ServerUnavailableError(f"Cannot connect to backend at {self.base_url}: {e}") from e
        except httpx.TimeoutException as e:
            raise ServerUnavailableError(f"Health check timed out: {e}") from e

    # ── SSE Streaming ─────────────────────────────────────────────────────────

    async def stream_events(
        self,
        execution_id: UUID | str,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Consume SSE stream for real-time execution updates.

        Connects to /stream/{execution_id} and yields each parsed event.

        Args:
            execution_id: Execution UUID to stream.

        Yields:
            Dict with 'event' (event type) and 'data' (parsed JSON payload).

        Raises:
            AuthenticationError: If API key is invalid.
            ServerUnavailableError: If stream connection fails.
        """
        url = f"{self.base_url}/stream/{execution_id}"
        headers = dict(self._build_headers())
        headers["Accept"] = "text/event-stream"

        # SSE uses query param for auth (headers limited in EventSource)
        params: dict[str, str] = {}
        if self.api_key:
            params["api_key"] = self.api_key

        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(self.sse_timeout, connect=10.0)) as sse_client:
                async with aconnect_sse(sse_client, "GET", url, headers=headers, params=params) as event_source:
                    async for sse in event_source.aiter_sse():
                        event_type = sse.event or "message"

                        # Parse JSON data payload
                        try:
                            data = json.loads(sse.data) if sse.data else {}
                        except json.JSONDecodeError:
                            data = {"raw": sse.data}

                        yield {"event": event_type, "data": data}

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                raise AuthenticationError(
                    "Authentication failed for SSE stream",
                    status_code=401,
                ) from e
            raise APIError(
                f"SSE stream error: HTTP {e.response.status_code}",
                status_code=e.response.status_code,
            ) from e
        except httpx.ConnectError as e:
            raise ServerUnavailableError(f"Cannot connect to SSE stream at {url}: {e}") from e
        except httpx.TimeoutException as e:
            raise ServerUnavailableError(f"SSE stream timed out: {e}") from e
