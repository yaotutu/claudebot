import json
from pathlib import Path

from claudebot.claude_code.config import ClaudeCodeConfig, PermissionMode
from claudebot.config.loader import load_config, save_config
from claudebot.config.schema import Config


def test_default_config_uses_empty_secret_without_crashing():
    cfg = ClaudeCodeConfig()

    assert cfg.to_env() == {"CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY": "1"}
    assert cfg.auth_mode() == "official_or_external"

    status = cfg.redacted_status()
    assert status["api_key"] == ""


def test_env_uses_anthropic_api_key_only():
    cfg = ClaudeCodeConfig(
        base_url="http://127.0.0.1:20128/v1",
        api_key="api-key-value",
        model="glm-cn/glm-5.1",
        enable_gateway_model_discovery=True,
    )

    env = cfg.to_env()

    assert env["ANTHROPIC_BASE_URL"] == "http://127.0.0.1:20128/v1"
    assert env["ANTHROPIC_API_KEY"] == "api-key-value"
    assert "ANTHROPIC_AUTH_TOKEN" not in env
    assert env["CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY"] == "1"


def test_env_passes_auth_token_when_api_key_is_not_configured(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "auth-token-value")
    cfg = ClaudeCodeConfig()

    env = cfg.to_env()

    assert env["ANTHROPIC_AUTH_TOKEN"] == "auth-token-value"
    assert "ANTHROPIC_API_KEY" not in env


def test_status_redacts_api_key():
    cfg = ClaudeCodeConfig(
        base_url="http://127.0.0.1:20128/v1",
        api_key="ak-secret",
        model="glm-cn/glm-5.1",
    )

    status = cfg.redacted_status()

    assert status["base_url"] == "http://127.0.0.1:20128/v1"
    assert status["auth_mode"] == "api_key"
    assert status["api_key"] == "ak-***"
    assert "secret" not in str(status)


def test_config_repr_and_str_do_not_expose_secrets():
    cfg = ClaudeCodeConfig(api_key="api-key-value")

    assert "api-key-value" not in repr(cfg)
    assert "api-key-value" not in str(cfg)


def test_model_dump_does_not_expose_plaintext_secrets():
    cfg = ClaudeCodeConfig(api_key="api-key-value")

    dumped = cfg.model_dump()

    assert dumped["api_key"] != "api-key-value"
    assert "api-key-value" not in str(dumped)


def test_permission_mode_values_match_claude_sdk():
    assert PermissionMode.READ_ONLY.value == "default"
    assert PermissionMode.EDIT.value == "acceptEdits"
    assert PermissionMode.FULL.value == "bypassPermissions"


def test_top_level_config_accepts_claude_code_aliases():
    cfg = Config.model_validate(
        {
            "claudeCode": {
                "baseUrl": "http://127.0.0.1:20128/v1",
                "apiKey": "api-key",
                "model": "glm-cn/glm-5.1",
                "permissionMode": "bypassPermissions",
            },
            "workspace": {"path": "/tmp/workspace"},
        }
    )

    assert cfg.claude_code.base_url == "http://127.0.0.1:20128/v1"
    assert cfg.claude_code.api_key.get_secret_value() == "api-key"
    assert cfg.claude_code.model == "glm-cn/glm-5.1"
    assert cfg.workspace.path == "/tmp/workspace"
    assert cfg.workspace_path == Path("/tmp/workspace")


def test_top_level_config_accepts_claude_code_snake_case_alias():
    cfg = Config.model_validate(
        {
            "claude_code": {
                "baseUrl": "http://127.0.0.1:20128/v1",
                "apiKey": "api-key",
            }
        }
    )

    assert cfg.claude_code.base_url == "http://127.0.0.1:20128/v1"
    assert cfg.claude_code.api_key.get_secret_value() == "api-key"


def test_workspace_path_uses_workspace_path():
    cfg = Config.model_validate({"workspace": {"path": "/tmp/workspace-default"}})

    assert cfg.workspace_path == Path("/tmp/workspace-default")


def test_load_config_defaults_workspace_next_to_config(tmp_path):
    config_path = tmp_path / "instance" / "config.json"
    config_path.parent.mkdir()
    config_path.write_text('{"claudeCode": {"model": "test-model"}}', encoding="utf-8")

    cfg = load_config(config_path)

    assert cfg.workspace.path == ""
    assert cfg.workspace_path == config_path.parent / "workspace"


def test_load_config_overlays_claude_code_runtime_env(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://192.168.55.222:20128/v1")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "env-api-key")
    monkeypatch.setenv("CLAUDE_CODE_MODEL", "glm-cn/glm-5.1")
    monkeypatch.setenv("CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY", "1")
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "claudeCode": {
                    "baseUrl": "http://old.example/v1",
                    "apiKey": "file-api-key",
                    "model": "old-model",
                    "enableGatewayModelDiscovery": False,
                }
            }
        ),
        encoding="utf-8",
    )

    cfg = load_config(config_path)

    assert cfg.claude_code.base_url == "http://192.168.55.222:20128/v1"
    assert cfg.claude_code.api_key.get_secret_value() == "env-api-key"
    assert cfg.claude_code.model == "glm-cn/glm-5.1"
    assert cfg.claude_code.enable_gateway_model_discovery is True


def test_workspace_path_ignores_legacy_agent_workspace_override():
    cfg = Config.model_validate(
        {
            "workspace": {"defaultPath": "/tmp/workspace-default"},
            "agents": {"defaults": {"workspace": "/tmp/agent-override"}},
        }
    )

    assert cfg.workspace_path == Path("/tmp/workspace-default")


def test_save_load_config_preserves_claude_code_api_key(tmp_path):
    config_path = tmp_path / "config.json"
    config = Config(claude_code=ClaudeCodeConfig(api_key="api-key"))

    save_config(config, config_path)
    saved = json.loads(config_path.read_text(encoding="utf-8"))
    reloaded = load_config(config_path)

    assert "authToken" not in saved["claudeCode"]
    assert saved["claudeCode"]["apiKey"] == "api-key"
    assert "**********" not in config_path.read_text(encoding="utf-8")
    assert reloaded.claude_code.api_key.get_secret_value() == "api-key"
