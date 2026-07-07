"""
Tests for the /admin/* endpoints.

Covers mode management, tool listing/refresh, and admin-level
authorization requirements.
"""

from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient


class TestAdminMode:
    """Tests for GET /admin/mode and POST /admin/mode endpoints."""

    @pytest.mark.asyncio
    async def test_get_mode(
        self,
        test_client: AsyncClient,
        admin_headers: dict[str, str],
    ) -> None:
        """Get current execution mode configuration."""
        response = await test_client.get("/admin/mode", headers=admin_headers)

        assert response.status_code == 200
        data = response.json()
        assert "global_mode" in data
        assert data["global_mode"] in ("mock", "live", "mixed")
        assert "effective_mode" in data
        assert "server_modes" in data
        assert isinstance(data["server_modes"], dict)
        assert "active_executions" in data
        assert "can_switch_at_runtime" in data
        assert data["can_switch_at_runtime"] is True

    @pytest.mark.asyncio
    async def test_set_mode(
        self,
        test_client: AsyncClient,
        admin_headers: dict[str, str],
    ) -> None:
        """Switch execution mode with admin token returns 200."""
        response = await test_client.post(
            "/admin/mode",
            json={
                "global_mode": "mixed",
                "reason": "Testing mixed mode",
            },
            headers=admin_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert "previous_mode" in data
        assert "new_mode" in data
        assert data["new_mode"] == "mixed"
        assert "applied_at" in data

    @pytest.mark.asyncio
    async def test_set_mode_with_server_overrides(
        self,
        test_client: AsyncClient,
        admin_headers: dict[str, str],
    ) -> None:
        """Set mode with per-server overrides."""
        response = await test_client.post(
            "/admin/mode",
            json={
                "global_mode": "mixed",
                "server_overrides": {
                    "github": "live",
                    "aws-ecs": "mock",
                },
                "reason": "Enable GitHub live, keep AWS mocked",
            },
            headers=admin_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["new_mode"] == "mixed"

    @pytest.mark.asyncio
    async def test_set_mode_unauthorized(
        self,
        test_client: AsyncClient,
        api_headers: dict[str, str],
    ) -> None:
        """Standard API key on admin endpoint returns 403."""
        response = await test_client.post(
            "/admin/mode",
            json={
                "global_mode": "live",
                "reason": "Should fail",
            },
            headers=api_headers,  # Regular API key, not admin token
        )

        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_set_mode_no_auth(self, test_client: AsyncClient) -> None:
        """Admin endpoint without any auth returns 401."""
        response = await test_client.post(
            "/admin/mode",
            json={"global_mode": "live", "reason": "Should fail"},
        )

        assert response.status_code == 401


class TestAdminTools:
    """Tests for GET /admin/tools and POST /admin/tools/refresh endpoints."""

    @pytest.mark.asyncio
    async def test_list_tools(
        self,
        test_client: AsyncClient,
        admin_headers: dict[str, str],
    ) -> None:
        """List available MCP tools with admin token."""
        response = await test_client.get("/admin/tools", headers=admin_headers)

        assert response.status_code == 200
        data = response.json()
        assert "last_refreshed_at" in data
        assert "server_count" in data
        assert "total_tools" in data
        assert "servers" in data
        assert isinstance(data["servers"], list)

        for server in data["servers"]:
            assert "server_name" in server
            assert "transport" in server
            assert "connected" in server
            assert "mode" in server
            assert "tool_count" in server
            assert "tools" in server

            for tool in server["tools"]:
                assert "name" in tool
                assert "description" in tool
                assert "input_schema" in tool

    @pytest.mark.asyncio
    async def test_list_tools_unauthorized(
        self,
        test_client: AsyncClient,
        api_headers: dict[str, str],
    ) -> None:
        """Standard API key on admin tools endpoint returns 403."""
        response = await test_client.get("/admin/tools", headers=api_headers)
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_refresh_tools(
        self,
        test_client: AsyncClient,
        admin_headers: dict[str, str],
    ) -> None:
        """Refresh tool registry with admin token."""
        response = await test_client.post(
            "/admin/tools/refresh",
            headers=admin_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert "refreshed_at" in data
        assert "servers_discovered" in data
        assert "tools_discovered" in data
        assert "servers" in data

    @pytest.mark.asyncio
    async def test_refresh_tools_unauthorized(
        self,
        test_client: AsyncClient,
        api_headers: dict[str, str],
    ) -> None:
        """Standard API key on refresh endpoint returns 403."""
        response = await test_client.post(
            "/admin/tools/refresh",
            headers=api_headers,
        )
        assert response.status_code == 403


class TestAdminAuthorizationEdgeCases:
    """Edge cases for admin authorization."""

    @pytest.mark.asyncio
    async def test_admin_with_invalid_bearer_token(
        self,
        test_client: AsyncClient,
    ) -> None:
        """Invalid bearer token returns 401."""
        response = await test_client.get(
            "/admin/mode",
            headers={"Authorization": "Bearer invalid-token"},
        )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_admin_with_malformed_auth_header(
        self,
        test_client: AsyncClient,
    ) -> None:
        """Malformed Authorization header returns 401."""
        response = await test_client.get(
            "/admin/mode",
            headers={"Authorization": "NotBearer token"},
        )
        assert response.status_code == 401
