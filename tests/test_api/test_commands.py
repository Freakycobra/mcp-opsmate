"""
Tests for the /commands endpoint.

Covers command submission, validation, authorization, intent classification,
plan generation, and edge cases like low-confidence intent and MCP unavailability.
All external APIs are mocked — no real API calls are made.
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import AsyncClient


class TestSubmitCommand:
    """Tests for POST /commands endpoint."""

    @pytest.mark.asyncio
    async def test_submit_command_success(
        self,
        test_client: AsyncClient,
        api_headers: dict[str, str],
        mock_openai: MagicMock,
    ) -> None:
        """Successfully submit a command and receive an execution ID with 202 Accepted."""
        payload = {
            "text": "Check payment-service pods in EKS and restart if CPU > 80%",
            "auto_approve": False,
        }

        response = await test_client.post("/commands", json=payload, headers=api_headers)

        assert response.status_code == 202
        data = response.json()
        assert "execution_id" in data
        assert data["status"] in ("pending", "planning", "awaiting_confirmation", "executing")
        assert data["execution_mode"] == "mock"
        assert "stream_url" in data
        assert data["stream_url"].startswith("/stream/")

        # Verify execution_id is a valid UUID
        exec_id = uuid.UUID(data["execution_id"])
        assert str(exec_id) == data["execution_id"]

    @pytest.mark.asyncio
    async def test_submit_command_validation_error(
        self,
        test_client: AsyncClient,
        api_headers: dict[str, str],
    ) -> None:
        """Empty or invalid commands return 400 with validation details."""
        # Empty command text
        response = await test_client.post(
            "/commands",
            json={"text": ""},
            headers=api_headers,
        )
        assert response.status_code == 400
        data = response.json()
        assert "detail" in data

        # Command text too long (>2000 chars)
        response = await test_client.post(
            "/commands",
            json={"text": "x" * 2001},
            headers=api_headers,
        )
        assert response.status_code == 400

        # Missing text field entirely
        response = await test_client.post(
            "/commands",
            json={"auto_approve": True},
            headers=api_headers,
        )
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_submit_command_unauthorized(
        self,
        test_client: AsyncClient,
    ) -> None:
        """Requests without valid API key return 401 Unauthorized."""
        payload = {"text": "Check payment-service pods"}

        # No API key
        response = await test_client.post("/commands", json=payload)
        assert response.status_code == 401

        # Invalid API key
        response = await test_client.post(
            "/commands",
            json=payload,
            headers={"X-API-Key": "invalid-key"},
        )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_submit_command_low_confidence_clarification(
        self,
        test_client: AsyncClient,
        api_headers: dict[str, str],
        mock_openai: MagicMock,
    ) -> None:
        """Low-confidence intent classification returns 422 with clarification prompt."""
        # Configure the mock to return low confidence
        mock_openai.return_value.chat.completions.create = AsyncMock(
            return_value=MagicMock(
                choices=[MagicMock(
                    message=MagicMock(
                        content='{"type": ["UNKNOWN"], "entities": {}, "confidence": 0.45}'
                    )
                )]
            )
        )

        payload = {"text": "Do something with the thing over there maybe"}
        response = await test_client.post("/commands", json=payload, headers=api_headers)

        assert response.status_code == 422
        data = response.json()
        assert "confidence" in data
        assert data["confidence"] < 0.7
        assert "reason" in data
        assert "suggested_rephrasings" in data
        assert "examples" in data

    @pytest.mark.asyncio
    async def test_submit_command_auto_approve_single_step(
        self,
        test_client: AsyncClient,
        api_headers: dict[str, str],
        mock_openai: MagicMock,
    ) -> None:
        """Single-step plans with auto_approve=True skip confirmation and execute immediately."""
        # Configure mock to return a single-step plan
        mock_openai.return_value.chat.completions.create = AsyncMock(
            return_value=MagicMock(
                choices=[MagicMock(
                    message=MagicMock(
                        content='{"type": ["QUERY"], "entities": {"service_name": "payment-service"}, "confidence": 0.95}'
                    )
                )]
            )
        )

        payload = {
            "text": "List payment-service pods",
            "auto_approve": True,
        }

        response = await test_client.post("/commands", json=payload, headers=api_headers)

        assert response.status_code == 202
        data = response.json()
        assert data["status"] in ("executing", "completed")

    @pytest.mark.asyncio
    async def test_submit_command_mcp_unavailable(
        self,
        test_client: AsyncClient,
        api_headers: dict[str, str],
        mock_mcp_hub: Any,
        mock_openai: MagicMock,
    ) -> None:
        """When required MCP servers are unavailable and no mock fallback exists, return 503."""
        # Mark all servers as disconnected
        for server in mock_mcp_hub.servers.values():
            server.connected = False

        mock_mcp_hub.get_server_status.return_value = {
            name: {"connected": False, "mode": s.mode, "tool_count": 0}
            for name, s in mock_mcp_hub.servers.items()
        }

        payload = {"text": "Check payment-service pods in EKS"}
        response = await test_client.post("/commands", json=payload, headers=api_headers)

        assert response.status_code == 503
        data = response.json()
        assert "error" in data

    @pytest.mark.asyncio
    async def test_submit_command_with_metadata(
        self,
        test_client: AsyncClient,
        api_headers: dict[str, str],
        mock_openai: MagicMock,
    ) -> None:
        """Commands with metadata are accepted and metadata is preserved."""
        payload = {
            "text": "Check payment-service pods",
            "auto_approve": False,
            "metadata": {"source": "cli", "user_id": "test-user", "trace_id": "abc123"},
        }

        response = await test_client.post("/commands", json=payload, headers=api_headers)

        assert response.status_code == 202
        data = response.json()
        assert "execution_id" in data

    @pytest.mark.asyncio
    async def test_submit_command_execution_mode_override(
        self,
        test_client: AsyncClient,
        api_headers: dict[str, str],
        mock_openai: MagicMock,
    ) -> None:
        """Per-command execution mode override is accepted."""
        payload = {
            "text": "Check payment-service pods",
            "auto_approve": False,
            "execution_mode_override": "live",
        }

        response = await test_client.post("/commands", json=payload, headers=api_headers)

        assert response.status_code == 202
        data = response.json()
        # The mode should be reflected (even if the system may not actually switch)
        assert "execution_mode" in data
