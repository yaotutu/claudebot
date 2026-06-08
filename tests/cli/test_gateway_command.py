from typer.testing import CliRunner

from claudebot.cli.commands import app


def test_gateway_accepts_host_override(monkeypatch):
    captured = {}

    def fake_load_runtime_config(config, workspace):
        captured["config_arg"] = config
        captured["workspace_arg"] = workspace
        return object()

    def fake_run_gateway(config, *, port=None, host=None):
        captured["config"] = config
        captured["port"] = port
        captured["host"] = host

    monkeypatch.setattr("claudebot.cli.commands._load_runtime_config", fake_load_runtime_config)
    monkeypatch.setattr("claudebot.cli.commands._run_gateway", fake_run_gateway)

    result = CliRunner().invoke(app, ["gateway", "--host", "0.0.0.0", "--port", "18790"])

    assert result.exit_code == 0
    assert captured["host"] == "0.0.0.0"
    assert captured["port"] == 18790
