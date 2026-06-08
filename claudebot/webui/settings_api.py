"""Settings REST helpers for the WebUI HTTP surface.

The WebSocket channel owns transport/authentication. This module owns the
settings payload shape and the allowlisted config mutations exposed to WebUI.
"""

from __future__ import annotations

import os
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from claudebot.claude_code.config import ClaudeCodeConfig, PermissionMode
from claudebot.config.loader import get_config_path, load_config, save_config
from claudebot.security.workspace_access import workspace_sandbox_status
from claudebot.webui.token_usage import token_usage_payload
from claudebot.webui.workspaces import (
    read_webui_default_access_mode,
    write_webui_default_access_mode,
)

QueryParams = dict[str, list[str]]
SettingsInput = QueryParams | dict[str, Any]

_BROWSER_RESTART_BEHAVIOR_BY_SECTION = {
    "appearance": "none",
    "models": "none",
    "runtime": "engineRestart",
    "browser": "engineRestart",
    "apps": "engineRestart",
    "advanced": "appRestart",
}


class WebUISettingsError(ValueError):
    """User-facing settings validation failure."""

    def __init__(self, message: str, *, status: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


def _cfg_get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def restart_behavior_by_section() -> dict[str, str]:
    return dict(_BROWSER_RESTART_BEHAVIOR_BY_SECTION)


def decorate_settings_payload(
    payload: dict[str, Any],
    *,
    restart_required_sections: list[str] | None = None,
    apply_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Attach runtime-surface metadata without changing the core settings shape."""
    sections = restart_required_sections
    if sections is None:
        raw_sections = payload.get("restart_required_sections") or []
        sections = [str(section) for section in raw_sections if isinstance(section, str)]
    sections = sorted(dict.fromkeys(sections))
    result = dict(payload)
    result["restart_behavior_by_section"] = restart_behavior_by_section()
    result["restart_required_sections"] = sections
    if sections:
        result["requires_restart"] = True
    else:
        result["requires_restart"] = bool(result.get("requires_restart", False))
    result["apply_state"] = apply_state or {
        "status": "pending" if result["requires_restart"] else "idle",
        "sections": sections,
    }
    return result


def _query_first(query: QueryParams, key: str) -> str | None:
    values = query.get(key)
    return values[0] if values else None


def _input_get(data: SettingsInput, *keys: str) -> Any:
    for key in keys:
        if key in data:
            value = data[key]
            if isinstance(value, list):
                return value[0] if value else None
            return value
    return None


def _input_has(data: SettingsInput, *keys: str) -> bool:
    return any(key in data for key in keys)


def _query_first_alias(query: QueryParams, snake: str, camel: str) -> str | None:
    value = _query_first(query, snake)
    return _query_first(query, camel) if value is None else value


def _parse_bool(value: str, field: str) -> bool:
    normalized = value.strip().lower()
    if normalized not in {"1", "0", "true", "false", "yes", "no"}:
        raise WebUISettingsError(f"{field} must be boolean")
    return normalized in {"1", "true", "yes"}


def settings_payload(
    *,
    requires_restart: bool = False,
    restart_required_sections: list[str] | None = None,
    apply_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    config = load_config()
    defaults = config.agents.defaults
    claude = config.claude_code
    claude_api_key = _secret_value(claude.api_key) or os.environ.get("ANTHROPIC_API_KEY", "")

    exec_config = config.tools.exec
    sandbox_status = workspace_sandbox_status(
        restrict_to_workspace=config.tools.restrict_to_workspace,
        workspace=config.workspace_path,
    )
    payload = {
        "agent": {
            "model": claude.model,
            "has_api_key": bool(claude_api_key),
            "max_tokens": defaults.max_tokens,
            "context_window_tokens": defaults.context_window_tokens,
            "temperature": defaults.temperature,
            "reasoning_effort": defaults.reasoning_effort,
            "timezone": defaults.timezone,
            "bot_name": defaults.bot_name,
            "bot_icon": defaults.bot_icon,
            "tool_hint_max_length": defaults.tool_hint_max_length,
        },
        "runtime": {
            "config_path": str(get_config_path().expanduser()),
            "workspace_path": str(config.workspace_path),
            "gateway_host": config.gateway.host,
            "gateway_port": config.gateway.port,
            "heartbeat": {
                "enabled": config.gateway.heartbeat.enabled,
                "interval_s": config.gateway.heartbeat.interval_s,
                "keep_recent_messages": config.gateway.heartbeat.keep_recent_messages,
            },
            "dream": {
                "schedule": defaults.dream.describe_schedule(),
            },
            "unified_session": defaults.unified_session,
        },
        "usage": token_usage_payload(timezone_name=defaults.timezone),
        "advanced": {
            "restrict_to_workspace": config.tools.restrict_to_workspace,
            "workspace_sandbox": sandbox_status.as_dict(),
            "webui_allow_local_service_access": config.tools.webui_allow_local_service_access,
            "allow_local_preview_access": config.tools.webui_allow_local_service_access,
            "webui_default_access_mode": read_webui_default_access_mode(),
            "private_service_protection_enabled": True,
            "ssrf_whitelist_count": len(config.tools.ssrf_whitelist),
            "mcp_server_count": len(config.tools.mcp_servers),
            "exec_enabled": _cfg_get(exec_config, "enable", True),
            "exec_sandbox": _cfg_get(exec_config, "sandbox", None) or None,
            "exec_path_append_set": bool(_cfg_get(exec_config, "path_append", [])),
        },
        "requires_restart": requires_restart,
    }
    return decorate_settings_payload(
        payload,
        restart_required_sections=restart_required_sections,
        apply_state=apply_state,
    )


def settings_usage_payload() -> dict[str, Any]:
    """Return the lightweight token usage slice for Overview refreshes."""
    config = load_config()
    return token_usage_payload(timezone_name=config.agents.defaults.timezone)


def _secret_value(value: Any) -> str:
    get_secret_value = getattr(value, "get_secret_value", None)
    if callable(get_secret_value):
        return str(get_secret_value())
    return str(value or "")


def _claude_code_config_payload(config: Any) -> dict[str, Any]:
    claude = config.claude_code
    status = claude.redacted_status()
    return {
        "baseUrl": status["base_url"],
        "authMode": status["auth_mode"],
        "apiKey": status["api_key"],
        "model": status["model"],
        "permissionMode": status["permission_mode"],
        "enableGatewayModelDiscovery": status["enable_gateway_model_discovery"],
        "maxTurns": status["max_turns"],
    }


def claude_code_health_payload() -> dict[str, Any]:
    config = load_config()
    claude = config.claude_code
    last_error = ""

    models_endpoint_reachable = False
    base_url = claude.base_url.rstrip("/")
    if base_url:
        headers: dict[str, str] = {}
        api_key = _secret_value(claude.api_key)
        if api_key:
            headers["x-api-key"] = api_key
        try:
            response = httpx.get(f"{base_url}/models", headers=headers, timeout=3)
            models_endpoint_reachable = response.status_code < 500
            if response.status_code >= 400:
                last_error = f"models endpoint returned HTTP {response.status_code}"
        except Exception as exc:
            if not last_error:
                last_error = str(exc)

    return {
        "sdkRuntime": True,
        "modelsEndpointReachable": models_endpoint_reachable,
        "lastError": last_error,
    }


def claude_code_settings_payload() -> dict[str, Any]:
    config = load_config()
    return {
        "claudeCode": _claude_code_config_payload(config),
        "health": claude_code_health_payload(),
    }


def update_claude_code_settings(data: SettingsInput) -> dict[str, Any]:
    config = load_config()
    current = config.claude_code
    values = {
        "base_url": current.base_url,
        "api_key": _secret_value(current.api_key),
        "model": current.model,
        "permission_mode": current.permission_mode,
        "enable_gateway_model_discovery": current.enable_gateway_model_discovery,
        "max_turns": current.max_turns,
    }

    mapping = {
        "base_url": ("baseUrl", "base_url"),
        "api_key": ("apiKey", "api_key"),
        "model": ("model",),
    }
    for field, keys in mapping.items():
        if _input_has(data, *keys):
            values[field] = str(_input_get(data, *keys) or "").strip()

    if _input_has(data, "permissionMode", "permission_mode"):
        try:
            values["permission_mode"] = PermissionMode(
                str(_input_get(data, "permissionMode", "permission_mode") or "").strip()
            )
        except ValueError as exc:
            raise WebUISettingsError("invalid permission mode") from exc

    if _input_has(data, "enableGatewayModelDiscovery", "enable_gateway_model_discovery"):
        raw_discovery = _input_get(
            data,
            "enableGatewayModelDiscovery",
            "enable_gateway_model_discovery",
        )
        if isinstance(raw_discovery, bool):
            values["enable_gateway_model_discovery"] = raw_discovery
        else:
            values["enable_gateway_model_discovery"] = _parse_bool(
                str(raw_discovery or ""),
                "enableGatewayModelDiscovery",
            )

    if _input_has(data, "maxTurns", "max_turns"):
        try:
            values["max_turns"] = int(_input_get(data, "maxTurns", "max_turns"))
        except (TypeError, ValueError) as exc:
            raise WebUISettingsError("maxTurns must be an integer") from exc

    try:
        config.claude_code = ClaudeCodeConfig(**values)
    except Exception as exc:
        raise WebUISettingsError(str(exc)) from exc
    save_config(config)
    return claude_code_settings_payload()


def update_agent_settings(query: QueryParams) -> dict[str, Any]:
    config = load_config()
    defaults = config.agents.defaults
    changed = False
    restart_required = False

    timezone = _query_first(query, "timezone")
    if timezone is not None:
        timezone = timezone.strip()
        if not timezone:
            raise WebUISettingsError("timezone is required")
        try:
            ZoneInfo(timezone)
        except Exception:
            raise WebUISettingsError("invalid timezone") from None
        if defaults.timezone != timezone:
            defaults.timezone = timezone
            changed = True
            restart_required = True

    bot_name = _query_first_alias(query, "bot_name", "botName")
    if bot_name is not None:
        bot_name = bot_name.strip()
        if not bot_name:
            raise WebUISettingsError("bot_name is required")
        if defaults.bot_name != bot_name:
            defaults.bot_name = bot_name
            changed = True
            restart_required = True

    bot_icon = _query_first_alias(query, "bot_icon", "botIcon")
    if bot_icon is not None:
        bot_icon = bot_icon.strip()
        if defaults.bot_icon != bot_icon:
            defaults.bot_icon = bot_icon
            changed = True
            restart_required = True

    tool_hint_max_length = _query_first_alias(
        query,
        "tool_hint_max_length",
        "toolHintMaxLength",
    )
    if tool_hint_max_length is not None:
        try:
            parsed = int(tool_hint_max_length)
        except ValueError:
            raise WebUISettingsError("tool_hint_max_length must be an integer") from None
        if parsed < 20 or parsed > 500:
            raise WebUISettingsError("tool_hint_max_length must be between 20 and 500")
        if defaults.tool_hint_max_length != parsed:
            defaults.tool_hint_max_length = parsed
            changed = True
            restart_required = True

    if changed:
        save_config(config)
    return settings_payload(requires_restart=restart_required)


def update_network_safety_settings(query: QueryParams) -> dict[str, Any]:
    config = load_config()
    changed = False

    local_access = _query_first_alias(
        query,
        "webui_allow_local_service_access",
        "webuiAllowLocalServiceAccess",
    )
    if local_access is not None:
        parsed = _parse_bool(local_access, "webui_allow_local_service_access")
        if config.tools.webui_allow_local_service_access != parsed:
            config.tools.webui_allow_local_service_access = parsed
            changed = True

    access_mode = _query_first_alias(
        query,
        "webui_default_access_mode",
        "webuiDefaultAccessMode",
    )
    if access_mode is not None:
        normalized = access_mode.strip()
        if normalized not in {"default", "full"}:
            raise WebUISettingsError("webui_default_access_mode must be default or full")
        if read_webui_default_access_mode() != normalized:
            write_webui_default_access_mode(normalized)
            changed = True

    if changed:
        save_config(config)
    return settings_payload(requires_restart=changed)
