import json
from pathlib import Path

import pytest

from claudebot.claude_code.project import (
    SYSTEM_MEMORY_END,
    SYSTEM_MEMORY_START,
    USER_SOUL_END,
    USER_SOUL_START,
    sync_claude_project,
)
from claudebot.config.schema import Config, MCPServerConfig


def test_sync_claude_project_creates_runtime_layout(tmp_path: Path):
    workspace = tmp_path / "workspace"
    config = Config.model_validate({"workspace": {"path": str(workspace)}})

    result = sync_claude_project(config, config_path=tmp_path / "config.json")

    assert result.workspace_path == workspace
    assert (workspace / "CLAUDE.md").exists()
    assert (workspace / ".claude" / "settings.json").exists()
    assert (workspace / ".claude" / "skills").is_dir()
    assert (workspace / ".claude" / "agent" / "sessions").is_dir()
    assert (workspace / ".claude" / "agent" / "memory" / "chats").is_dir()
    manifest = json.loads(
        (workspace / ".claude" / "agent" / "generated-manifest.json").read_text(encoding="utf-8")
    )
    assert ".claude/settings.json" in manifest["files"]
    assert ".mcp.json" in manifest["files"]
    assert ".claude/skills/builtin-cron" in manifest["files"]
    assert "builtin-cron" in manifest["skills"]["builtin"]

    mcp = json.loads((workspace / ".mcp.json").read_text(encoding="utf-8"))
    runtime = mcp["mcpServers"]["agent_runtime"]
    assert runtime["type"] == "stdio"
    assert runtime["args"] == ["-m", "claudebot.agent_runtime.server"]
    assert runtime["env"]["CLAUDEBOT_WORKSPACE"] == str(workspace)
    skill_md = workspace / ".claude" / "skills" / "builtin-cron" / "SKILL.md"
    assert "name: builtin-cron" in skill_md.read_text(encoding="utf-8")


def test_sync_claude_project_creates_claude_md_template(tmp_path: Path):
    workspace = tmp_path / "workspace"
    config = Config.model_validate({"workspace": {"path": str(workspace)}})

    sync_claude_project(config)

    text = (workspace / "CLAUDE.md").read_text(encoding="utf-8")
    assert USER_SOUL_START in text
    assert USER_SOUL_END in text
    assert SYSTEM_MEMORY_START in text
    assert SYSTEM_MEMORY_END in text


def test_sync_claude_project_backs_up_damaged_claude_md(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    claude_md = workspace / "CLAUDE.md"
    claude_md.write_text("old user content", encoding="utf-8")
    config = Config.model_validate({"workspace": {"path": str(workspace)}})

    sync_claude_project(config)

    assert USER_SOUL_START in claude_md.read_text(encoding="utf-8")
    backups = list(workspace.glob("CLAUDE.md.bak.*"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == "old user content"


def test_sync_claude_project_refuses_unmanaged_settings_file(tmp_path: Path):
    workspace = tmp_path / "workspace"
    settings = workspace / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text("{}", encoding="utf-8")
    config = Config.model_validate({"workspace": {"path": str(workspace)}})

    with pytest.raises(RuntimeError, match="not managed"):
        sync_claude_project(config)


def test_sync_claude_project_writes_mcp_json_from_config(tmp_path: Path):
    workspace = tmp_path / "workspace"
    config = Config.model_validate({"workspace": {"path": str(workspace)}})
    config.tools.mcp_servers["example"] = MCPServerConfig(
        type="stdio",
        command="node",
        args=["server.js"],
        env={"TOKEN": "${TOKEN}"},
    )

    sync_claude_project(config)

    mcp = json.loads((workspace / ".mcp.json").read_text(encoding="utf-8"))
    assert "agent_runtime" in mcp["mcpServers"]
    assert mcp["mcpServers"]["example"] == {
        "type": "stdio",
        "command": "node",
        "args": ["server.js"],
        "env": {"TOKEN": "${TOKEN}"},
    }
    manifest = json.loads(
        (workspace / ".claude" / "agent" / "generated-manifest.json").read_text(encoding="utf-8")
    )
    assert ".mcp.json" in manifest["files"]


def test_sync_claude_project_reserves_agent_runtime_mcp_name(tmp_path: Path):
    workspace = tmp_path / "workspace"
    config = Config.model_validate({"workspace": {"path": str(workspace)}})
    config.tools.mcp_servers["agent_runtime"] = MCPServerConfig(command="node")

    with pytest.raises(RuntimeError, match="reserved"):
        sync_claude_project(config)


def test_sync_claude_project_skips_disabled_builtin_skills(tmp_path: Path):
    workspace = tmp_path / "workspace"
    config = Config.model_validate(
        {
            "workspace": {"path": str(workspace)},
            "agents": {"defaults": {"disabledSkills": ["cron"]}},
        }
    )

    sync_claude_project(config)

    assert not (workspace / ".claude" / "skills" / "builtin-cron").exists()


def test_sync_claude_project_refuses_unmanaged_builtin_skill_dir(tmp_path: Path):
    workspace = tmp_path / "workspace"
    skill_dir = workspace / ".claude" / "skills" / "builtin-cron"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nname: builtin-cron\n---\n", encoding="utf-8")
    config = Config.model_validate({"workspace": {"path": str(workspace)}})

    with pytest.raises(RuntimeError, match="not managed"):
        sync_claude_project(config)
