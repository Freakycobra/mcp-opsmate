"""CLI configuration management.

Configuration resolution order (later overrides earlier):
1. Default values in code
2. ~/.opsmate/config.yaml file
3. Environment variables (OPS_MATE_* prefix)
4. CLI flags / runtime overrides
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


DEFAULT_CONFIG_DIR = Path.home() / ".opsmate"
DEFAULT_CONFIG_FILE = DEFAULT_CONFIG_DIR / "config.yaml"
DEFAULT_HISTORY_FILE = DEFAULT_CONFIG_DIR / "history"


class OpsmateConfig(BaseSettings):
    """CLI configuration with layered resolution.

    Environment variables (OPS_MATE_* prefix) override file config.
    """

    model_config = SettingsConfigDict(
        env_prefix="OPS_MATE_",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── API Settings ──────────────────────────────────────────────────────────
    api_url: str = Field(default="http://localhost:8000", description="Base URL for the FastAPI backend")
    api_key: str | None = Field(default=None, description="API key for authentication (X-API-Key header)")
    admin_token: str | None = Field(default=None, description="Admin bearer token for admin endpoints")
    timeout: float = Field(default=30.0, description="HTTP request timeout in seconds")
    sse_timeout: float = Field(default=300.0, description="SSE stream timeout in seconds")

    # ── Display Settings ──────────────────────────────────────────────────────
    theme: str = Field(default="default", description="Rich theme name")
    output_format: str = Field(default="table", description="Default output format: table, json, markdown")
    no_color: bool = Field(default=False, description="Disable colored output")
    verbose: bool = Field(default=False, description="Enable verbose output")

    # ── Behavior Settings ─────────────────────────────────────────────────────
    auto_approve: bool = Field(default=False, description="Auto-approve all plans")
    default_mode: str = Field(default="mock", description="Default execution mode: mock, live, mixed")
    history_limit: int = Field(default=100, description="Maximum history entries to keep")
    interactive_confirm: bool = Field(default=True, description="Confirm destructive actions in interactive mode")

    # ── Paths ─────────────────────────────────────────────────────────────────
    config_dir: Path = Field(default=DEFAULT_CONFIG_DIR)
    config_file: Path = Field(default=DEFAULT_CONFIG_FILE)
    history_file: Path = Field(default=DEFAULT_HISTORY_FILE)

    def model_post_init(self, __context: Any) -> None:
        """Ensure config directory exists."""
        self.config_dir.mkdir(parents=True, exist_ok=True)

    # ── File I/O ──────────────────────────────────────────────────────────────

    @classmethod
    def from_file(cls, path: Path | None = None) -> "OpsmateConfig":
        """Load configuration from YAML file, merging with defaults.

        Args:
            path: Path to config YAML file. Defaults to ~/.opsmate/config.yaml.

        Returns:
            OpsmateConfig instance with file values merged over defaults.
        """
        config_path = path or DEFAULT_CONFIG_FILE
        kwargs: dict[str, Any] = {}

        if config_path.exists():
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    file_data = yaml.safe_load(f) or {}

                # Flatten nested dicts (e.g., api.url -> api_url)
                flat_data = cls._flatten(file_data)
                kwargs.update(flat_data)
            except (yaml.YAMLError, OSError) as e:
                # Log warning but continue with defaults
                print(f"[warning] Could not read config file {config_path}: {e}")

        return cls(**kwargs)

    def save_to_file(self, path: Path | None = None) -> None:
        """Save current configuration to YAML file.

        Args:
            path: Path to save config. Defaults to self.config_file.
        """
        config_path = path or self.config_file
        config_path.parent.mkdir(parents=True, exist_ok=True)

        data = {
            "api": {
                "url": self.api_url,
                "timeout": self.timeout,
                "sse_timeout": self.sse_timeout,
            },
            "display": {
                "theme": self.theme,
                "output_format": self.output_format,
                "no_color": self.no_color,
                "verbose": self.verbose,
            },
            "behavior": {
                "auto_approve": self.auto_approve,
                "default_mode": self.default_mode,
                "history_limit": self.history_limit,
                "interactive_confirm": self.interactive_confirm,
            },
        }

        # Never write secrets to file
        with open(config_path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _flatten(nested: dict[str, Any], prefix: str = "") -> dict[str, Any]:
        """Flatten nested dict into dot-separated keys, then convert to snake_case.

        Example: {"api": {"url": "..."}} -> {"api_url": "..."}
        """
        result: dict[str, Any] = {}
        for key, value in nested.items():
            full_key = f"{prefix}_{key}" if prefix else key
            if isinstance(value, dict):
                result.update(OpsmateConfig._flatten(value, full_key))
            else:
                result[full_key] = value
        return result

    def get_auth_headers(self) -> dict[str, str]:
        """Return HTTP headers for API authentication.

        Returns:
            Dict with X-API-Key header if api_key is configured.
        """
        headers: dict[str, str] = {}
        if self.api_key:
            headers["X-API-Key"] = self.api_key
        return headers

    def get_admin_headers(self) -> dict[str, str]:
        """Return HTTP headers for admin endpoint authentication.

        Returns:
            Dict with Authorization Bearer header if admin_token is configured.
        """
        headers = self.get_auth_headers()
        if self.admin_token:
            headers["Authorization"] = f"Bearer {self.admin_token}"
        return headers

    def set(self, key: str, value: Any) -> None:
        """Set a configuration value at runtime.

        Args:
            key: Configuration key name.
            value: Value to set.

        Raises:
            AttributeError: If key is not a valid config field.
        """
        if not hasattr(self, key):
            raise AttributeError(f"Unknown config key: {key}")
        # Type conversion for common cases
        if key in ("timeout", "sse_timeout"):
            value = float(value)
        elif key in ("no_color", "verbose", "auto_approve", "interactive_confirm"):
            value = str(value).lower() in ("true", "1", "yes", "on")
        elif key == "history_limit":
            value = int(value)
        setattr(self, key, value)

    def as_table_data(self) -> list[tuple[str, str, str]]:
        """Return config as list of (section, key, value) tuples for display.

        Returns:
            List of (section, key, value) tuples.
        """
        return [
            ("API", "api_url", self.api_url),
            ("API", "api_key", "***" if self.api_key else "(not set)"),
            ("API", "timeout", str(self.timeout)),
            ("API", "sse_timeout", str(self.sse_timeout)),
            ("Display", "theme", self.theme),
            ("Display", "output_format", self.output_format),
            ("Display", "no_color", str(self.no_color)),
            ("Display", "verbose", str(self.verbose)),
            ("Behavior", "auto_approve", str(self.auto_approve)),
            ("Behavior", "default_mode", self.default_mode),
            ("Behavior", "history_limit", str(self.history_limit)),
            ("Behavior", "interactive_confirm", str(self.interactive_confirm)),
        ]


# ── Global Config Instance ────────────────────────────────────────────────────

_config: OpsmateConfig | None = None


def get_config() -> OpsmateConfig:
    """Get the global configuration singleton.

    Returns:
        OpsmateConfig instance (cached).
    """
    global _config
    if _config is None:
        _config = OpsmateConfig.from_file()
    return _config


def reload_config() -> OpsmateConfig:
    """Reload configuration from file and environment.

    Returns:
        Fresh OpsmateConfig instance.
    """
    global _config
    _config = OpsmateConfig.from_file()
    return _config
