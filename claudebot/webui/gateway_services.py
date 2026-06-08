"""Composition helpers for the embedded WebUI gateway."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from loguru import logger as default_logger

from claudebot.claude_code.runner import ClaudeCodeRunner
from claudebot.claude_code.sessions import ClaudeCodeSessionStore
from claudebot.webui.gateway_tokens import GatewayTokenStore
from claudebot.webui.media_gateway import WebUIMediaGateway
from claudebot.webui.transcript import WebUITranscriptRecorder
from claudebot.webui.workspaces import WebUIWorkspaceController
from claudebot.webui.ws_http import GatewayHTTPHandler


@dataclass(frozen=True)
class GatewayServices:
    """Explicit dependencies shared by WebSocket transport and HTTP routes."""

    http: GatewayHTTPHandler
    tokens: GatewayTokenStore
    media: WebUIMediaGateway
    transcripts: WebUITranscriptRecorder
    workspaces: WebUIWorkspaceController
    session_manager: Any | None
    cron_service: Any | None
    claude_runner: Any | None = None
    claude_sessions: Any | None = None
    claude_permission_mode: Any | None = None


def build_gateway_services(
    *,
    config: Any,
    bus: Any,
    session_manager: Any | None,
    static_dist_path: Path | None,
    workspace_path: Path,
    default_restrict_to_workspace: bool,
    runtime_model_name: Any | None,
    disabled_skills: set[str] | None = None,
    cron_service: Any | None = None,
    claude_config: Any | None = None,
    claude_runner: Any | None = None,
    claude_sessions: Any | None = None,
    logger: Any = default_logger,
) -> GatewayServices:
    tokens = GatewayTokenStore()
    media = WebUIMediaGateway(
        workspace_path=workspace_path,
        logger=logger,
    )
    transcripts = WebUITranscriptRecorder(log=logger)
    workspaces = WebUIWorkspaceController(
        session_manager=session_manager,
        default_workspace=workspace_path,
        default_restrict_to_workspace=default_restrict_to_workspace,
    )
    http = GatewayHTTPHandler(
        config=config,
        session_manager=session_manager,
        static_dist_path=static_dist_path,
        runtime_model_name=runtime_model_name,
        bus=bus,
        tokens=tokens,
        media=media,
        workspaces=workspaces,
        skills_workspace_path=workspace_path,
        disabled_skills=disabled_skills,
        cron_service=cron_service,
        log=logger,
    )
    if claude_config is None:
        claude_config = getattr(config, "claude_code", None)
    if claude_runner is None and claude_config is not None:
        claude_runner = ClaudeCodeRunner(claude_config)
    if claude_sessions is None and claude_config is not None:
        claude_sessions = ClaudeCodeSessionStore(workspace_path)
    return GatewayServices(
        http=http,
        tokens=tokens,
        media=media,
        transcripts=transcripts,
        workspaces=workspaces,
        session_manager=session_manager,
        cron_service=cron_service,
        claude_runner=claude_runner,
        claude_sessions=claude_sessions,
        claude_permission_mode=getattr(claude_config, "permission_mode", None),
    )
