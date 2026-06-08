"""Runtime data paths under the Claude project workspace."""

from __future__ import annotations

from pathlib import Path


def agent_dir(workspace: Path) -> Path:
    return workspace / ".claude" / "agent"


def schedules_path(workspace: Path) -> Path:
    return agent_dir(workspace) / "schedules.json"
