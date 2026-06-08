import pytest
from pydantic import ValidationError

from claudebot.config.schema import Config


def test_claude_code_model_is_the_configured_runtime_model() -> None:
    config = Config.model_validate(
        {
            "claudeCode": {
                "baseUrl": "http://127.0.0.1:20128/v1",
                "apiKey": "api-key",
                "model": "glm-cn/glm-5.1",
            }
        }
    )

    assert config.claude_code.base_url == "http://127.0.0.1:20128/v1"
    assert config.claude_code.api_key.get_secret_value() == "api-key"
    assert config.claude_code.model == "glm-cn/glm-5.1"


@pytest.mark.parametrize("legacy_key", ["providers", "modelPresets", "model_presets"])
def test_legacy_provider_and_model_preset_roots_are_rejected(legacy_key: str) -> None:
    with pytest.raises(ValidationError, match=legacy_key):
        Config.model_validate({legacy_key: {}})


@pytest.mark.parametrize("legacy_key", ["model", "provider", "modelPreset", "fallbackModels"])
def test_legacy_agent_model_fields_are_ignored(legacy_key: str) -> None:
    config = Config.model_validate({"agents": {"defaults": {legacy_key: "legacy"}}})

    assert not hasattr(config.agents.defaults, "model")
    assert not hasattr(config.agents.defaults, "provider")
    assert not hasattr(config.agents.defaults, "model_preset")
    assert not hasattr(config.agents.defaults, "fallback_models")
