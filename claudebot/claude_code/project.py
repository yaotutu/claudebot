"""Generate Claude Code project files from claudebot config."""

from __future__ import annotations

import json
import re
import shutil
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from claudebot.brand import env_name

BUILTIN_SKILLS_DIR = Path(__file__).parent.parent / "skills"
USER_SOUL_START = "<!-- USER:SOUL:START -->"
USER_SOUL_END = "<!-- USER:SOUL:END -->"
SYSTEM_MEMORY_START = "<!-- SYSTEM:MEMORY:START -->"
SYSTEM_MEMORY_END = "<!-- SYSTEM:MEMORY:END -->"


@dataclass(slots=True)
class GeneratedProjectFiles:
    workspace_path: Path
    claude_dir: Path
    agent_dir: Path
    claude_md: Path
    settings_json: Path
    manifest_json: Path
    mcp_json: Path | None


def sync_claude_project(config: Any, *, config_path: Path | None = None) -> GeneratedProjectFiles:
    """Synchronize generated Claude project files for the configured workspace."""
    workspace = Path(config.workspace_path).expanduser()
    workspace.mkdir(parents=True, exist_ok=True)

    claude_dir = workspace / ".claude"
    agent_dir = claude_dir / "agent"
    settings_json = claude_dir / "settings.json"
    manifest_json = agent_dir / "generated-manifest.json"
    claude_md = workspace / "CLAUDE.md"

    for directory in (
        claude_dir,
        claude_dir / "skills",
        agent_dir,
        agent_dir / "sessions",
        agent_dir / "memory",
        agent_dir / "memory" / "chats",
    ):
        directory.mkdir(parents=True, exist_ok=True)

    manifest = _load_manifest(manifest_json)
    generated_files = set(manifest.get("files", []))

    _write_generated_json(
        workspace=workspace,
        relative_path=".claude/settings.json",
        path=settings_json,
        payload={},
        generated_files=generated_files,
    )

    mcp_path = _sync_mcp_json(config, workspace=workspace, generated_files=generated_files)
    builtin_skills = _sync_builtin_skills(
        config,
        skills_dir=claude_dir / "skills",
        generated_files=generated_files,
    )
    _ensure_claude_md(claude_md)

    files = [".claude/settings.json"]
    if mcp_path is not None:
        files.append(".mcp.json")
    files.extend(f".claude/skills/{name}" for name in builtin_skills)

    _write_json(
        manifest_json,
        {
            "version": 1,
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "sourceConfig": str(config_path.expanduser()) if config_path is not None else "",
            "files": files,
            "skills": {"builtin": builtin_skills, "external": []},
        },
    )

    return GeneratedProjectFiles(
        workspace_path=workspace,
        claude_dir=claude_dir,
        agent_dir=agent_dir,
        claude_md=claude_md,
        settings_json=settings_json,
        manifest_json=manifest_json,
        mcp_json=mcp_path,
    )


def _load_manifest(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _sync_mcp_json(config: Any, *, workspace: Path, generated_files: set[str]) -> Path | None:
    servers = getattr(getattr(config, "tools", None), "mcp_servers", {}) or {}
    path = workspace / ".mcp.json"
    agent_dir = workspace / ".claude" / "agent"
    payload: dict[str, Any] = {
        "mcpServers": {
            "agent_runtime": {
                "type": "stdio",
                "command": sys.executable,
                "args": ["-m", "claudebot.agent_runtime.server"],
                "env": {
                    env_name("WORKSPACE"): str(workspace),
                    env_name("AGENT_DIR"): str(agent_dir),
                },
            }
        }
    }
    for name, server in servers.items():
        if name == "agent_runtime":
            raise RuntimeError("MCP server name 'agent_runtime' is reserved")
        if hasattr(server, "model_dump"):
            raw = server.model_dump(mode="json", exclude_none=True)
        elif isinstance(server, dict):
            raw = dict(server)
        else:
            continue
        payload["mcpServers"][name] = {
            key: value
            for key, value in raw.items()
            if value not in ("", [], {}, None) and key not in {"tool_timeout", "enabled_tools"}
        }

    _write_generated_json(
        workspace=workspace,
        relative_path=".mcp.json",
        path=path,
        payload=payload,
        generated_files=generated_files,
    )
    return path


def _write_generated_json(
    *,
    workspace: Path,
    relative_path: str,
    path: Path,
    payload: dict[str, Any],
    generated_files: set[str],
) -> None:
    if path.exists() and relative_path not in generated_files:
        raise RuntimeError(
            f"{path} already exists but is not managed by claudebot; remove it or add a generated manifest"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_json(path, payload)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _sync_builtin_skills(
    config: Any,
    *,
    skills_dir: Path,
    generated_files: set[str],
) -> list[str]:
    disabled = set(
        getattr(getattr(getattr(config, "agents", None), "defaults", None), "disabled_skills", [])
        or []
    )
    if not BUILTIN_SKILLS_DIR.exists():
        return []

    generated: list[str] = []
    for source in sorted(BUILTIN_SKILLS_DIR.iterdir(), key=lambda item: item.name):
        if not source.is_dir() or not (source / "SKILL.md").is_file():
            continue
        if source.name in disabled or f"builtin-{source.name}" in disabled:
            continue
        dest_name = f"builtin-{source.name}"
        relative = f".claude/skills/{dest_name}"
        dest = skills_dir / dest_name
        if dest.exists() and relative not in generated_files:
            raise RuntimeError(f"{dest} already exists but is not managed by claudebot")
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(source, dest)
        skill_file = dest / "SKILL.md"
        skill_file.write_text(
            _rewrite_skill_name(skill_file.read_text(encoding="utf-8"), dest_name),
            encoding="utf-8",
        )
        generated.append(dest_name)
    return generated


def _rewrite_skill_name(markdown: str, name: str) -> str:
    if markdown.startswith("---"):
        updated = re.sub(
            r"(?m)^name:\s*.+$",
            f"name: {name}",
            markdown,
            count=1,
        )
        if updated != markdown:
            return updated
    return f"---\nname: {name}\n---\n\n{markdown}"


def _ensure_claude_md(path: Path) -> None:
    if not path.exists():
        path.write_text(_claude_md_template(), encoding="utf-8")
        return

    text = path.read_text(encoding="utf-8")
    if _has_claude_markers(text):
        return

    backup = path.with_name(
        f"{path.name}.bak.{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
    )
    path.replace(backup)
    path.write_text(_claude_md_template(), encoding="utf-8")


def _has_claude_markers(text: str) -> bool:
    return all(
        marker in text
        for marker in (
            USER_SOUL_START,
            USER_SOUL_END,
            SYSTEM_MEMORY_START,
            SYSTEM_MEMORY_END,
        )
    )


def _claude_md_template() -> str:
    return f"""# CLAUDE.md

## Soul

{USER_SOUL_START}
You are my personal agent.
{USER_SOUL_END}

## Memory

{SYSTEM_MEMORY_START}
No workspace memory has been summarized yet.
{SYSTEM_MEMORY_END}
"""
