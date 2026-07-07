"""
Tests for the /executions endpoints.

Covers listing executions with filtering, retrieving execution details,
and approving/rejecting pending execution plans.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone, timedelta
from typing import Any

import pytest
from httpx import AsyncClient

from opsmate.core.models import ExecutionStatus, ExecutionMode


class TestListExecutions:
    """Tests for GET /executions endpoint."""

    @pytest.mark.asyncio
    async def test_list_executions(
        self,
        test_client: AsyncClient,
        api_headers: dict[str, str],
        mock_openai: Any,
    ) -> None:
        """List executions returns paginated results with execution summaries."""
        # First, create an execution by submitting a command
        await test_client.post(
            "/commands",
            json={"text": "Check payment-service pods"},
            headers=api_headers,
        )

        # List executions
        response = await test_client.get("/executions", headers=api_headers)

        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert "total" in data
        assert "page" in data
        assert "page_size" in data
        assert "total_pages" in data
        assert isinstance(data["items"], list)

    @pytest.mark.asyncio
    async def test_list_executions_with_filter(
        self,
        test_client: AsyncClient,
        api_headers: dict[str, str],
        mock_openai: Any,
    ) -> None:
        """List executions supports filtering by status, mode, and date range."""
        # Create a couple executions
        await test_client.post(
            "/commands",
            json={"text": "Check payment-service pods"},
            headers=api_headers,
        )

        # Filter by status
        response = await test_client.get(
            "/executions?status=completed",
            headers=api_headers,
        )
        assert response.status_code == 200

        # Filter by mode
        response = await test_client.get(
            "/executions?mode=mock",
            headers=api_headers,
        )
        assert response.status_code == 200

        # Filter by date range
        from_date = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        to_date = datetime.now(timezone.utc).isoformat()
        response = await test_client.get(
            f"/executions?from_date={from_date}&to_date={to_date}",
            headers=api_headers,
        )
        assert response.status_code == 200

        # Filter with pagination
        response = await test_client.get(
            "/executions?page=1&page_size=10",
            headers=api_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["page"] == 1
        assert data["page_size"] == 10

    @pytest.mark.asyncio
    async def test_list_executions_unauthorized(
        self,
        test_client: AsyncClient,
    ) -> None:
        """Unauthorized requests to list executions return 401."""
        response = await test_client.get("/executions")
        assert response.status_code == 401


class TestGetExecutionDetail:
    """Tests for GET /executions/{execution_id} endpoint."""

    @pytest.mark.asyncio
    async def test_get_execution_detail(
        self,
        test_client: AsyncClient,
        api_headers: dict[str, str],
        mock_openai: Any,
    ) -> None:
        """Get full execution detail including plan, results, and context."""
        # Create an execution
        create_response = await test_client.post(
            "/commands",
            json={"text": "Check payment-service pods"},
            headers=api_headers,
        )
        exec_id = create_response.json()["execution_id"]

        # Get execution detail
        response = await test_client.get(
            f"/executions/{exec_id}",
            headers=api_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["execution_id"] == exec_id
        assert "status" in data
        assert "command_text" in data
        assert "execution_mode" in data
        assert "plan" in data
        assert "results" in data
        assert "context" in data
        assert "created_at" in data
        assert "updated_at" in data

    @pytest.mark.asyncio
    async def test_get_execution_not_found(
        self,
        test_client: AsyncClient,
        api_headers: dict[str, str],
    ) -> None:
        """Requesting a non-existent execution returns 404."""
        fake_id = str(uuid.uuid4())
        response = await test_client.get(
            f"/executions/{fake_id}",
            headers=api_headers,
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_get_execution_unauthorized(
        self,
        test_client: AsyncClient,
    ) -> None:
        """Unauthorized requests return 401."""
        fake_id = str(uuid.uuid4())
        response = await test_client.get(f"/executions/{fake_id}")
        assert response.status_code == 401


class TestApproveExecution:
    """Tests for POST /executions/{id}/approve endpoint."""

    @pytest.mark.asyncio
    async def test_approve_execution(
        self,
        test_client: AsyncClient,
        api_headers: dict[str, str],
        mock_openai: Any,
    ) -> None:
        """Approve a pending execution plan and transition to executing state."""
        # Create a multi-step execution (will need approval)
        create_response = await test_client.post(
            "/commands",
            json={"text": "Check payment-service pods, restart if CPU > 80%, alert Slack"},
            headers=api_headers,
        )
        exec_id = create_response.json()["execution_id"]

        # Approve the execution
        response = await test_client.post(
            f"/executions/{exec_id}/approve",
            json={"decision": "approve"},
            headers=api_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["execution_id"] == exec_id
        assert data["decision"] == "approve"

    @pytest.mark.asyncio
    async def test_reject_execution(
        self,
        test_client: AsyncClient,
        api_headers: dict[str, str],
        mock_openai: Any,
    ) -> None:
        """Reject a pending execution plan and transition to cancelled state."""
        # Create a multi-step execution
        create_response = await test_client.post(
            "/commands",
            json={"text": "Check payment-service pods, restart if CPU > 80%, alert Slack"},
            headers=api_headers,
        )
        exec_id = create_response.json()["execution_id"]

        # Reject the execution
        response = await test_client.post(
            f"/executions/{exec_id}/approve",
            json={"decision": "reject", "reason": "Too risky"},
            headers=api_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["decision"] == "reject"

    @pytest.mark.asyncio
    async def test_approve_execution_not_found(
        self,
        test_client: AsyncClient,
        api_headers: dict[str, str],
    ) -> None:
        """Approving a non-existent execution returns 404."""
        fake_id = str(uuid.uuid4())
        response = await test_client.post(
            f"/executions/{fake_id}/approve",
            json={"decision": "approve"},
            headers=api_headers,
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_approve_execution_wrong_state(
        self,
        test_client: AsyncClient,
        api_headers: dict[str, str],
        mock_openai: Any,
    ) -> None:
        """Approving an execution not in AWAITING_CONFIRMATION state returns 409."""
        # Create and auto-approve a single-step execution
        create_response = await test_client.post(
            "/commands",
            json={"text": "List tables", "auto_approve": True},
            headers=api_headers,
        )
        exec_id = create_response.json()["execution_id"]

        # Try to approve an already-executed execution
        response = await test_client.post(
            f"/executions/{exec_id}/approve",
            json={"decision": "approve"},
            headers=api_headers,
        )

        assert response.status_code == 409

    @pytest.mark.asyncio
    async def test_approve_execution_unauthorized(
        self,
        test_client: AsyncClient,
    ) -> None:
        """Unauthorized approval attempts return 401."""
        fake_id = str(uuid.uuid4())
        response = await test_client.post(
            f"/executions/{fake_id}/approve",
            json={"decision": "approve"},
        )
        assert response.status_code == 401
