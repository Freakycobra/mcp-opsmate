"""
Tests for the /health and /metrics endpoints.

Covers health checks with and without MCP server status,
and Prometheus metrics endpoint validation.
"""

from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient


class TestHealthEndpoint:
    """Tests for GET /health endpoint."""

    @pytest.mark.asyncio
    async def test_health_endpoint(self, test_client: AsyncClient) -> None:
        """Health endpoint returns 200 with system status when all services are healthy."""
        response = await test_client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert data["status"] in ("healthy", "degraded", "unhealthy")
        assert "version" in data
        assert "uptime_seconds" in data
        assert "timestamp" in data
        assert "checks" in data
        assert isinstance(data["checks"], dict)

    @pytest.mark.asyncio
    async def test_health_with_mcp_status(
        self,
        test_client: AsyncClient,
        mock_mcp_hub: Any,
    ) -> None:
        """Health response includes MCP server connection status in checks."""
        response = await test_client.get("/health")

        assert response.status_code == 200
        data = response.json()
        checks = data["checks"]

        # Verify MCP server entries exist in checks
        mcp_checks = [k for k in checks.keys() if k.startswith("mcp-")]
        assert len(mcp_checks) > 0, "Expected MCP server health checks"

        for check_name, check_data in checks.items():
            if check_name.startswith("mcp-"):
                assert "status" in check_data
                assert check_data["status"] in ("ok", "warning", "critical")

    @pytest.mark.asyncio
    async def test_health_no_auth_required(self, test_client: AsyncClient) -> None:
        """Health endpoint does not require authentication."""
        response = await test_client.get("/health")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_health_response_time_under_threshold(
        self,
        test_client: AsyncClient,
    ) -> None:
        """Health endpoint responds within 2 seconds (NFR-27)."""
        import time

        start = time.monotonic()
        response = await test_client.get("/health")
        elapsed_ms = (time.monotonic() - start) * 1000

        assert response.status_code == 200
        assert elapsed_ms < 2000, f"Health check took {elapsed_ms:.0f}ms, expected <2000ms"


class TestMetricsEndpoint:
    """Tests for GET /metrics endpoint."""

    @pytest.mark.asyncio
    async def test_metrics_endpoint(self, test_client: AsyncClient) -> None:
        """Metrics endpoint returns Prometheus-formatted metrics."""
        response = await test_client.get("/metrics")

        assert response.status_code == 200
        content = response.text

        # Verify it's Prometheus text format
        assert "# TYPE" in content or "# HELP" in content or "_total" in content

        # Check for expected metric families
        expected_metrics = [
            "opsmate_requests_total",
            "opsmate_executions_total",
            "opsmate_mcp_server_connected",
        ]
        for metric in expected_metrics:
            assert metric in content, f"Expected metric '{metric}' not found in /metrics"

    @pytest.mark.asyncio
    async def test_metrics_no_auth_required(self, test_client: AsyncClient) -> None:
        """Metrics endpoint does not require authentication."""
        response = await test_client.get("/metrics")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_metrics_content_type(self, test_client: AsyncClient) -> None:
        """Metrics endpoint returns correct Content-Type header."""
        response = await test_client.get("/metrics")
        content_type = response.headers.get("content-type", "")
        assert "text/plain" in content_type
