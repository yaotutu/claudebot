"""Claude Code runtime configuration."""

from __future__ import annotations

import os
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator


class PermissionMode(str, Enum):
    READ_ONLY = "default"
    EDIT = "acceptEdits"
    FULL = "bypassPermissions"


class ClaudeCodeConfig(BaseModel):
    base_url: str = Field(default="", alias="baseUrl")
    api_key: SecretStr = Field(default="", alias="apiKey")
    model: str = "glm-cn/glm-5.1"
    permission_mode: PermissionMode = Field(default=PermissionMode.FULL, alias="permissionMode")
    enable_gateway_model_discovery: bool = Field(
        default=True,
        alias="enableGatewayModelDiscovery",
    )
    max_turns: int = Field(default=200, alias="maxTurns", ge=1)

    model_config = ConfigDict(populate_by_name=True, validate_default=True)

    @field_validator("base_url", "api_key", "model", mode="before")
    @classmethod
    def _strip(cls, value: Any) -> Any:
        if isinstance(value, str):
            return value.strip()
        return value

    @staticmethod
    def _secret_value(value: SecretStr) -> str:
        return value.get_secret_value()

    def to_env(self) -> dict[str, str]:
        env: dict[str, str] = {}
        if self.base_url:
            env["ANTHROPIC_BASE_URL"] = self.base_url
        api_key = self._secret_value(self.api_key)
        if api_key:
            env["ANTHROPIC_API_KEY"] = api_key
        elif auth_token := os.environ.get("ANTHROPIC_AUTH_TOKEN", "").strip():
            env["ANTHROPIC_AUTH_TOKEN"] = auth_token
        if self.enable_gateway_model_discovery:
            env["CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY"] = "1"
        return env

    @staticmethod
    def _redact(value: str) -> str:
        if not value:
            return ""
        if len(value) <= 4:
            return "***"
        return f"{value[:3]}***"

    def auth_mode(self) -> str:
        if self._secret_value(self.api_key):
            return "api_key"
        return "official_or_external"

    def redacted_status(self) -> dict[str, Any]:
        return {
            "base_url": self.base_url,
            "auth_mode": self.auth_mode(),
            "api_key": self._redact(self._secret_value(self.api_key)),
            "model": self.model,
            "permission_mode": self.permission_mode.value,
            "enable_gateway_model_discovery": self.enable_gateway_model_discovery,
            "max_turns": self.max_turns,
        }
