"""MCP server for first-party personal-agent runtime state."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from claudebot.agent_runtime.paths import schedules_path
from claudebot.brand import env_name
from claudebot.cron.service import CronService
from claudebot.cron.types import CronSchedule

mcp = FastMCP(
    "agent_runtime",
    instructions=(
        "Manage claudebot runtime state for the current workspace. "
        "Use these tools instead of editing .claude/agent files directly."
    ),
)


def _workspace() -> Path:
    raw = os.environ.get(env_name("WORKSPACE")) or os.getcwd()
    return Path(raw).expanduser().resolve(strict=False)


def _cron() -> CronService:
    return CronService(schedules_path(_workspace()))


def _job_payload(job: Any) -> dict[str, Any]:
    return {
        "id": job.id,
        "name": job.name,
        "enabled": job.enabled,
        "schedule": {
            "kind": job.schedule.kind,
            "at_ms": job.schedule.at_ms,
            "every_ms": job.schedule.every_ms,
            "expr": job.schedule.expr,
            "tz": job.schedule.tz,
        },
        "payload": {
            "message": job.payload.message,
            "session_key": job.payload.session_key,
            "channel": job.payload.channel,
            "to": job.payload.to,
        },
        "state": {
            "next_run_at_ms": job.state.next_run_at_ms,
            "last_run_at_ms": job.state.last_run_at_ms,
            "last_status": job.state.last_status,
            "last_error": job.state.last_error,
        },
    }


@mcp.tool()
def list_schedules(session_key: str | None = None) -> dict[str, Any]:
    """List scheduled agent turns for this workspace, optionally filtered by session_key."""
    jobs = _cron().list_jobs(include_disabled=True)
    if session_key:
        jobs = [job for job in jobs if job.payload.session_key == session_key]
    return {"jobs": [_job_payload(job) for job in jobs if job.payload.kind == "agent_turn"]}


@mcp.tool()
def add_schedule(
    name: str,
    message: str,
    *,
    session_key: str,
    kind: str = "every",
    every_seconds: int | None = None,
    at_ms: int | None = None,
    cron_expr: str | None = None,
    tz: str | None = None,
    delete_after_run: bool = False,
) -> dict[str, Any]:
    """Create a scheduled agent turn for a WebUI session.

    Use the current session_key from the system prompt. Supported kind values:
    "every", "at", and "cron".
    """
    name = name.strip()
    message = message.strip()
    session_key = session_key.strip()
    if not name:
        raise ValueError("name is required")
    if not message:
        raise ValueError("message is required")
    if not session_key:
        raise ValueError("session_key is required")
    if not session_key.startswith("websocket:"):
        raise ValueError("session_key must be a websocket session key")

    if kind == "every":
        if not every_seconds or every_seconds <= 0:
            raise ValueError("every_seconds must be positive for every schedules")
        schedule = CronSchedule(kind="every", every_ms=every_seconds * 1000)
    elif kind == "at":
        if not at_ms or at_ms <= 0:
            raise ValueError("at_ms must be positive for at schedules")
        schedule = CronSchedule(kind="at", at_ms=at_ms)
    elif kind == "cron":
        if not cron_expr or not cron_expr.strip():
            raise ValueError("cron_expr is required for cron schedules")
        schedule = CronSchedule(kind="cron", expr=cron_expr.strip(), tz=tz or None)
    else:
        raise ValueError("kind must be every, at, or cron")

    chat_id = session_key.split(":", 1)[1]
    cron = _cron()
    job = cron.add_job(
        name=name,
        schedule=schedule,
        message=message,
        deliver=True,
        channel="websocket",
        to=chat_id,
        delete_after_run=delete_after_run,
        session_key=session_key,
    )
    cron.list_jobs(include_disabled=True)
    return {"job": _job_payload(job)}


@mcp.tool()
def remove_schedule(job_id: str) -> dict[str, Any]:
    """Remove a scheduled agent turn by id."""
    cron = _cron()
    status = cron.remove_job(job_id.strip())
    cron.list_jobs(include_disabled=True)
    return {"status": status}


@mcp.tool()
def set_schedule_enabled(job_id: str, enabled: bool) -> dict[str, Any]:
    """Enable or disable a scheduled agent turn by id."""
    cron = _cron()
    job = cron.enable_job(job_id.strip(), enabled=enabled)
    cron.list_jobs(include_disabled=True)
    if job is None:
        return {"status": "not_found"}
    return {"status": "updated", "job": _job_payload(job)}


def main() -> None:
    mcp.run("stdio")


if __name__ == "__main__":
    main()
