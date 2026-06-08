from __future__ import annotations

from types import SimpleNamespace

from claudebot.webui import mcp_presets_runtime


def test_mcp_preset_runtime_lines_are_disabled_for_gateway() -> None:
    msg = SimpleNamespace(
        content="use @browserbase",
        metadata={
            "mcp_presets": [
                {
                    "name": "browserbase",
                    "display_name": "Browserbase",
                    "transport": "streamableHttp",
                }
            ],
        },
    )

    lines = mcp_presets_runtime.runtime_lines(msg)

    assert lines == []


def test_mcp_preset_runtime_lines_do_not_warn_when_restart_needed() -> None:
    msg = SimpleNamespace(
        content="use @browserbase",
        metadata={
            "mcp_presets": [
                {
                    "name": "browserbase",
                    "display_name": "Browserbase",
                    "transport": "streamableHttp",
                }
            ],
        },
    )

    lines = mcp_presets_runtime.runtime_lines(msg)

    assert lines == []


def test_mcp_preset_runtime_lines_do_not_warn_when_connection_not_live() -> None:
    msg = SimpleNamespace(
        content="use @browserbase",
        metadata={
            "mcp_presets": [
                {
                    "name": "browserbase",
                    "display_name": "Browserbase",
                    "transport": "streamableHttp",
                }
            ],
        },
    )

    lines = mcp_presets_runtime.runtime_lines(msg)

    assert lines == []


def test_mcp_preset_session_extra_only_persists_structured_mentions() -> None:
    assert mcp_presets_runtime.session_extra({}) == {}
    assert (
        mcp_presets_runtime.session_extra(
            {
                "mcp_presets": [{"name": "browserbase"}],
            }
        )
        == {}
    )
