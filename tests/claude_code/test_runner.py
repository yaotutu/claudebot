from pathlib import Path
from typing import Any

import pytest
from claude_agent_sdk import ClaudeAgentOptions
from claude_agent_sdk.types import (
    AssistantMessage,
    ResultMessage,
    StreamEvent,
    TextBlock,
    ThinkingBlock,
    ToolUseBlock,
)

from claudebot.claude_code.config import ClaudeCodeConfig, PermissionMode
from claudebot.claude_code.events import EventKind
from claudebot.claude_code.runner import ClaudeCodeRunner
from claudebot.claude_code.sessions import ClaudeCodeChatRecord


def make_record(tmp_path: Path, *, claude_session_id: str = "") -> ClaudeCodeChatRecord:
    return ClaudeCodeChatRecord(
        chat_id="chat-1",
        workspace_path=str(tmp_path),
        permission_mode=PermissionMode.EDIT,
        claude_session_id=claude_session_id,
    )


class FakeClaudeClient:
    def __init__(self, messages: list[Any], options: ClaudeAgentOptions):
        self.messages = messages
        self.options = options
        self.connected = False
        self.disconnected = False
        self.interrupted = False
        self.prompt: str | None = None
        self.session_id: str | None = None

    async def connect(self) -> None:
        self.connected = True

    async def query(self, prompt: str, session_id: str = "default") -> None:
        self.prompt = prompt
        self.session_id = session_id

    async def receive_response(self):
        for message in self.messages:
            yield message

    async def interrupt(self) -> None:
        self.interrupted = True

    async def disconnect(self) -> None:
        self.disconnected = True


def fake_client_factory(messages: list[Any], captured: dict[str, Any] | None = None):
    def factory(options: ClaudeAgentOptions):
        client = FakeClaudeClient(messages, options)
        if captured is not None:
            captured["client"] = client
            captured["options"] = options
        return client

    return factory


@pytest.mark.asyncio
async def test_run_turn_emits_sdk_stream_events_updates_session_and_returns_final_text(
    tmp_path: Path,
):
    messages = [
        StreamEvent(
            uuid="event-1",
            session_id="session-1",
            event={
                "type": "content_block_delta",
                "delta": {"type": "text_delta", "text": "h"},
            },
        ),
        ResultMessage(
            subtype="success",
            duration_ms=10,
            duration_api_ms=8,
            is_error=False,
            num_turns=1,
            session_id="session-1",
            result="hi",
        ),
    ]
    emitted = []
    runner = ClaudeCodeRunner(
        ClaudeCodeConfig(model="test-model"),
        client_factory=fake_client_factory(messages),
    )
    record = make_record(tmp_path)

    result = await runner.run_turn(record, "hello", on_event=emitted.append)

    assert [event.kind for event in emitted] == [EventKind.TEXT_DELTA, EventKind.TURN_DONE]
    assert emitted[0].text == "h"
    assert result.final_text == "hi"
    assert result.session_id == "session-1"
    assert result.exit_code == 0
    assert record.claude_session_id == "session-1"


@pytest.mark.asyncio
async def test_runner_builds_sdk_options_from_config_and_record(tmp_path: Path):
    captured: dict[str, Any] = {}
    config = ClaudeCodeConfig(
        base_url="https://gateway.example",
        api_key="secret-key",
        model="test-model",
        max_turns=42,
    )
    runner = ClaudeCodeRunner(
        config,
        client_factory=fake_client_factory(
            [
                ResultMessage(
                    subtype="success",
                    duration_ms=1,
                    duration_api_ms=1,
                    is_error=False,
                    num_turns=1,
                    session_id="session-2",
                    result="done",
                )
            ],
            captured,
        ),
    )
    record = make_record(tmp_path, claude_session_id="existing-session")

    await runner.run_turn(record, "hello")

    client = captured["client"]
    options = captured["options"]
    assert client.prompt == "hello"
    assert client.session_id == "existing-session"
    assert client.connected is True
    assert client.disconnected is True
    assert options.cwd == tmp_path
    assert options.env["ANTHROPIC_BASE_URL"] == "https://gateway.example"
    assert options.env["ANTHROPIC_API_KEY"] == "secret-key"
    assert "ANTHROPIC_AUTH_TOKEN" not in options.env
    assert options.include_partial_messages is True
    assert options.max_turns == 42
    assert options.model == "test-model"
    assert options.permission_mode == "acceptEdits"
    assert options.resume == "existing-session"
    assert options.setting_sources == ["project"]
    assert options.system_prompt["preset"] == "claude_code"
    assert "personal agent runtime" in options.system_prompt["append"]


@pytest.mark.asyncio
async def test_run_turn_exposes_interrupt_handle(tmp_path: Path):
    captured: dict[str, Any] = {}
    runner = ClaudeCodeRunner(
        ClaudeCodeConfig(model="test-model"),
        client_factory=fake_client_factory(
            [
                ResultMessage(
                    subtype="success",
                    duration_ms=1,
                    duration_api_ms=1,
                    is_error=False,
                    num_turns=1,
                    session_id="session-1",
                    result="done",
                )
            ],
            captured,
        ),
    )
    handles = []

    async def on_handle(handle):
        handles.append(handle)
        await handle.interrupt()

    await runner.run_turn(make_record(tmp_path), "hello", on_handle=on_handle)

    assert len(handles) == 1
    assert handles[0].interrupted is True
    assert captured["client"].interrupted is True


@pytest.mark.asyncio
async def test_interrupted_error_result_returns_cancel_exit_code(tmp_path: Path):
    runner = ClaudeCodeRunner(
        ClaudeCodeConfig(model="test-model"),
        client_factory=fake_client_factory(
            [
                ResultMessage(
                    subtype="error_during_execution",
                    duration_ms=1,
                    duration_api_ms=1,
                    is_error=True,
                    num_turns=1,
                    session_id="session-1",
                    result="interrupted",
                    errors=["interrupted"],
                )
            ],
        ),
    )

    async def on_handle(handle):
        await handle.interrupt()

    result = await runner.run_turn(make_record(tmp_path), "hello", on_handle=on_handle)

    assert result.final_text == ""
    assert result.exit_code == 130


@pytest.mark.asyncio
async def test_runner_maps_assistant_tool_and_thinking_blocks(tmp_path: Path):
    emitted = []
    runner = ClaudeCodeRunner(
        ClaudeCodeConfig(model="test-model"),
        client_factory=fake_client_factory(
            [
                AssistantMessage(
                    content=[
                        ThinkingBlock(thinking="thinking", signature="sig"),
                        ToolUseBlock(id="tool-1", name="Read", input={"file_path": "x.py"}),
                        TextBlock(text="not emitted from assistant snapshot"),
                    ],
                    model="test-model",
                    session_id="session-1",
                ),
                ResultMessage(
                    subtype="success",
                    duration_ms=1,
                    duration_api_ms=1,
                    is_error=False,
                    num_turns=1,
                    session_id="session-1",
                    result="done",
                ),
            ]
        ),
    )

    await runner.run_turn(make_record(tmp_path), "hello", on_event=emitted.append)

    assert [event.kind for event in emitted] == [
        EventKind.THINKING_DELTA,
        EventKind.TOOL_START,
        EventKind.TURN_DONE,
    ]
    assert emitted[0].text == "thinking"
    assert emitted[1].tool_use_id == "tool-1"
    assert emitted[1].tool_name == "Read"
    assert emitted[1].tool_input == {"file_path": "x.py"}


@pytest.mark.asyncio
async def test_error_result_raises_after_emitting_error(tmp_path: Path):
    emitted = []
    runner = ClaudeCodeRunner(
        ClaudeCodeConfig(model="test-model"),
        client_factory=fake_client_factory(
            [
                ResultMessage(
                    subtype="error",
                    duration_ms=1,
                    duration_api_ms=1,
                    is_error=True,
                    num_turns=1,
                    session_id="session-1",
                    result="model failed",
                    errors=["model failed"],
                )
            ]
        ),
    )

    with pytest.raises(RuntimeError, match="model failed"):
        await runner.run_turn(make_record(tmp_path), "hello", on_event=emitted.append)

    assert [event.kind for event in emitted] == [EventKind.ERROR]
    assert emitted[0].text == "model failed"


@pytest.mark.asyncio
async def test_callback_errors_propagate(tmp_path: Path):
    callback_error = ValueError("callback failed")
    runner = ClaudeCodeRunner(
        ClaudeCodeConfig(model="test-model"),
        client_factory=fake_client_factory(
            [
                StreamEvent(
                    uuid="event-1",
                    session_id="session-1",
                    event={
                        "type": "content_block_delta",
                        "delta": {"type": "text_delta", "text": "h"},
                    },
                )
            ]
        ),
    )

    def on_event(_event):
        raise callback_error

    with pytest.raises(ValueError, match="callback failed") as exc_info:
        await runner.run_turn(make_record(tmp_path), "hello", on_event=on_event)

    assert exc_info.value is callback_error
