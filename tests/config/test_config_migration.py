import json
import socket
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from claudebot.config.loader import _migrate_config, load_config, save_config
from claudebot.config.schema import Config
from claudebot.security.network import validate_url_target


def _fake_resolve(host: str, results: list[str]):
    """Return a getaddrinfo mock that maps the given host to fake IP results."""

    def _resolver(hostname, port, family=0, type_=0):
        if hostname == host:
            return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", (ip, 0)) for ip in results]
        raise socket.gaierror(f"cannot resolve {hostname}")

    return _resolver


def test_load_config_keeps_max_tokens_and_ignores_legacy_memory_window(tmp_path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "agents": {
                    "defaults": {
                        "maxTokens": 1234,
                        "memoryWindow": 42,
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.agents.defaults.max_tokens == 1234
    assert config.agents.defaults.context_window_tokens == 65_536
    assert not hasattr(config.agents.defaults, "memory_window")


def test_save_config_writes_context_window_tokens_but_not_memory_window(tmp_path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "agents": {
                    "defaults": {
                        "maxTokens": 2222,
                        "memoryWindow": 30,
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    config = load_config(config_path)
    save_config(config, config_path)
    saved = json.loads(config_path.read_text(encoding="utf-8"))
    defaults = saved["agents"]["defaults"]

    assert defaults["maxTokens"] == 2222
    assert defaults["contextWindowTokens"] == 65_536
    assert "memoryWindow" not in defaults


def test_onboard_does_not_crash_with_legacy_memory_window(tmp_path, monkeypatch) -> None:
    config_path = tmp_path / "config.json"
    workspace = tmp_path / "workspace"
    config_path.write_text(
        json.dumps(
            {
                "agents": {
                    "defaults": {
                        "maxTokens": 3333,
                        "memoryWindow": 50,
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr("claudebot.config.loader.get_config_path", lambda: config_path)
    monkeypatch.setattr(
        "claudebot.cli.commands.get_workspace_path", lambda _workspace=None: workspace
    )

    from typer.testing import CliRunner

    from claudebot.cli.commands import app

    runner = CliRunner()
    result = runner.invoke(app, ["onboard"], input="n\n")

    assert result.exit_code == 0


def test_onboard_keeps_legacy_channel_config_without_plugin_registry(tmp_path, monkeypatch) -> None:
    config_path = tmp_path / "config.json"
    workspace = tmp_path / "workspace"
    config_path.write_text(
        json.dumps(
            {
                "channels": {
                    "qq": {
                        "enabled": False,
                        "appId": "",
                        "secret": "",
                        "allowFrom": [],
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr("claudebot.config.loader.get_config_path", lambda: config_path)
    monkeypatch.setattr(
        "claudebot.cli.commands.get_workspace_path", lambda _workspace=None: workspace
    )

    from typer.testing import CliRunner

    from claudebot.cli.commands import app

    runner = CliRunner()
    result = runner.invoke(app, ["onboard"], input="n\n")

    assert result.exit_code == 0
    saved = json.loads(config_path.read_text(encoding="utf-8"))
    assert saved["channels"]["qq"]["enabled"] is False
    assert "msgFormat" not in saved["channels"]["qq"]


def test_load_config_migrates_legacy_my_tool_keys(tmp_path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "tools": {
                    "myEnabled": False,
                    "mySet": True,
                }
            }
        ),
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.tools.my["enable"] is False
    assert config.tools.my["allowSet"] is True


def test_legacy_provider_roots_are_rejected_even_with_claude_code() -> None:
    data = {
        "providers": {"openai": {"apiKey": "sk-test"}},
        "claudeCode": {
            "baseUrl": "http://127.0.0.1:20128/v1",
            "apiKey": "api-key",
            "model": "glm-cn/glm-5.1",
        },
    }

    migrated = _migrate_config(data)

    assert migrated["claudeCode"] == data["claudeCode"]
    with pytest.raises(ValidationError, match="providers"):
        Config.model_validate(migrated)

    cfg = Config.model_validate({"claudeCode": migrated["claudeCode"]})
    assert cfg.claude_code.base_url == "http://127.0.0.1:20128/v1"
    assert cfg.claude_code.api_key.get_secret_value() == "api-key"


def test_save_config_rewrites_legacy_my_tool_keys(tmp_path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "tools": {
                    "myEnabled": False,
                    "mySet": True,
                }
            }
        ),
        encoding="utf-8",
    )

    config = load_config(config_path)
    save_config(config, config_path)
    saved = json.loads(config_path.read_text(encoding="utf-8"))

    tools = saved["tools"]
    assert "myEnabled" not in tools
    assert "mySet" not in tools
    assert tools["my"] == {"enable": False, "allowSet": True}


def test_new_my_tool_keys_take_precedence_over_legacy(tmp_path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "tools": {
                    "myEnabled": False,
                    "mySet": False,
                    "my": {"enable": True, "allowSet": True},
                }
            }
        ),
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.tools.my["enable"] is True
    assert config.tools.my["allowSet"] is True


def test_load_config_resets_ssrf_whitelist_when_next_config_is_empty(tmp_path) -> None:
    whitelisted = tmp_path / "whitelisted.json"
    whitelisted.write_text(
        json.dumps({"tools": {"ssrfWhitelist": ["100.64.0.0/10"]}}),
        encoding="utf-8",
    )
    defaulted = tmp_path / "defaulted.json"
    defaulted.write_text(json.dumps({}), encoding="utf-8")

    load_config(whitelisted)
    with patch(
        "claudebot.security.network.socket.getaddrinfo", _fake_resolve("ts.local", ["100.100.1.1"])
    ):
        ok, err = validate_url_target("http://ts.local/api")
        assert ok, err

    load_config(defaulted)
    with patch(
        "claudebot.security.network.socket.getaddrinfo", _fake_resolve("ts.local", ["100.100.1.1"])
    ):
        ok, _ = validate_url_target("http://ts.local/api")
        assert not ok


def test_load_config_defaults_local_service_access_to_enabled(tmp_path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({"tools": {}}), encoding="utf-8")

    config = load_config(config_path)

    assert config.tools.webui_allow_local_service_access is True


def test_load_config_accepts_legacy_local_preview_access(tmp_path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"tools": {"allowLocalPreviewAccess": False}}),
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.tools.webui_allow_local_service_access is False


@pytest.mark.parametrize("legacy_key", ["providers", "api", "imageGeneration"])
def test_legacy_root_config_keys_are_not_migrated(legacy_key: str) -> None:
    data = {legacy_key: {}}

    migrated = _migrate_config(data)

    assert migrated == data
    assert migrated is not data
    with pytest.raises(ValidationError, match=legacy_key):
        Config.model_validate(migrated)
