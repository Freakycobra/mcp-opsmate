"""Pydantic-Settings configuration for mcp-opsmate.

Uses layered resolution: default values -> config.yaml -> env vars (OPS_MATE_*) -> CLI flags.
"""

from __future__ import annotations

import os
from typing import Any, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from opsmate.core.models import (
    AppSettings,
    CacheSettings,
    DatabaseSettings,
    LLMSettings,
    LoggingSettings,
    MCPSettings,
)


class OpsMateConfig(BaseSettings):
    """Root configuration loaded via Pydantic-Settings.

    Resolution order: default values -> config.yaml -> env vars (OPS_MATE_*) -> CLI flags.
    """

    model_config = SettingsConfigDict(
        env_prefix="OPS_MATE_",
        env_nested_delimiter="__",
        yaml_file="config.yaml",
        extra="ignore",
        env_parse_none_str="null",
    )

    app: AppSettings = Field(default_factory=AppSettings)
    llm: LLMSettings = Field(default_factory=LLMSettings)
    mcp_servers: dict[str, MCPSettings] = Field(default_factory=_default_mcp_servers)
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    cache: CacheSettings = Field(default_factory=CacheSettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)

    # Auth
    api_key: str = Field(default="dev-api-key-change-in-production")
    admin_api_token: str = Field(default="dev-admin-token-change-in-production")

    @field_validator("api_key", "admin_api_token")
    @classmethod
    def _warn_default_keys(cls, v: str, info) -> str:  # type: ignore[no-untyped-def]
        """Warn when default keys are used in production."""
        import logging

        logger: logging.Logger = logging.getLogger(__name__)
        field_name: str = info.field_name or "unknown"
        defaults: set[str] = {
            "dev-api-key-change-in-production",
            "dev-admin-token-change-in-production",
        }
        if v in defaults:
            logger.warning(
                "Using default %s. This is insecure for production deployments.",
                field_name,
            )
        return v

    @property
    def is_production(self) -> bool:
        """Check if running in production mode."""
        env: str = os.environ.get("ENVIRONMENT", "development").lower()
        return env in ("production", "prod", "staging")

    @property
    def is_mock_default(self) -> bool:
        """Check if mock mode is the global default."""
        return self.app.execution_mode in ("mock", "mixed")

    def get_server_mode(self, server_name: str) -> Literal["mock", "live", "local"]:
        """Get execution mode for a specific MCP server."""
        if server_name in self.mcp_servers:
            return self.mcp_servers[server_name].mode
        return "mock"

    def get_server_timeout(self, server_name: str) -> int:
        """Get timeout for a specific MCP server."""
        if server_name in self.mcp_servers:
            return self.mcp_servers[server_name].timeout
        return 30

    def resolve_execution_mode(
        self,
        server_name: str,
        request_override: Literal["mock", "live", "mixed"] | None = None,
    ) -> Literal["mock", "live", "local"]:
        """Resolve execution mode with priority: per-call > server config > global default.

        Args:
            server_name: Name of the MCP server.
            request_override: Optional per-call mode override.

        Returns:
            Resolved execution mode for the server.
        """
        # Priority 1: per-call override
        if request_override is not None:
            if request_override == "mixed":
                # In mixed with per-call override, use server config or mock
                return self.get_server_mode(server_name)
            return request_override

        # Priority 2: server config
        server_mode: Literal["mock", "live", "local"] = self.get_server_mode(server_name)
        if server_mode != "mock":
            return server_mode

        # Priority 3: global default
        global_mode: str = self.app.execution_mode
        if global_mode == "mixed":
            return "mock"
        if global_mode == "live":
            return "live"
        return "mock"


def _default_mcp_servers() -> dict[str, MCPSettings]:
    """Create default MCP server configurations."""
    return {
        "tavily-search": MCPSettings(
            transport="stdio",
            command=["python", "-m", "opsmate.mcp_servers.tavily"],
            mode="mock",
            timeout=30,
        ),
        "github": MCPSettings(
            transport="stdio",
            command=["python", "-m", "opsmate.mcp_servers.github"],
            mode="mock",
            timeout=30,
        ),
        "slack": MCPSettings(
            transport="stdio",
            command=["python", "-m", "opsmate.mcp_servers.slack"],
            mode="mock",
            timeout=15,
        ),
        "jira": MCPSettings(
            transport="stdio",
            command=["python", "-m", "opsmate.mcp_servers.jira"],
            mode="mock",
            timeout=30,
        ),
        "aws-ecs": MCPSettings(
            transport="stdio",
            command=["python", "-m", "opsmate.mcp_servers.aws_ecs"],
            mode="mock",
            timeout=60,
            critical=True,
        ),
        "postgres-db": MCPSettings(
            transport="stdio",
            command=["python", "-m", "opsmate.mcp_servers.postgres"],
            mode="live",
            timeout=30,
        ),
        "calculator": MCPSettings(
            transport="stdio",
            command=["python", "-m", "opsmate.mcp_servers.calculator"],
            mode="local",
            timeout=5,
            critical=True,
        ),
    }


# Global singleton
_config_instance: OpsMateConfig | None = None


def get_config() -> OpsMateConfig:
    """Get or create the global OpsMateConfig singleton."""
    global _config_instance
    if _config_instance is None:
        _config_instance = OpsMateConfig()
    return _config_instance


def reload_config() -> OpsMateConfig:
    """Force reload configuration from environment."""
    global _config_instance
    _config_instance = OpsMateConfig()
    return _config_instance
