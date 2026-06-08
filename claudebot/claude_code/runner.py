"""Claude Agent SDK runtime runner."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient
from claude_agent_sdk.types import (
    AssistantMessage,
    ResultMessage,
    ServerToolResultBlock,
    ServerToolUseBlock,
    StreamEvent,
    SystemMessage,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)

from claudebot.claude_code.config import ClaudeCodeConfig
from claudebot.claude_code.events import ClaudeCodeEvent, ClaudeCodeEventAdapter, EventKind
from claudebot.claude_code.sessions import ClaudeCodeChatRecord

ClientFactory = Callable[[ClaudeAgentOptions], Any]

_RUNTIME_SYSTEM_PROMPT = """\
You are running inside a personal agent runtime.

Use the current workspace as the boundary for all file operations. Do not access files outside the
workspace. Do not edit .claude/agent directly; use agent_runtime capabilities when they are
available. Do not modify the user's config file or runtime credentials.
"""


@dataclass(slots=True)
class ClaudeCodeRunResult:
    final_text: str
    session_id: str
    exit_code: int


class ClaudeCodeTurnHandle:
    """Handle for a running Claude Code SDK client turn."""

    def __init__(self, client: Any):
        self.client = client
        self.interrupted = False

    async def interrupt(self) -> None:
        interrupt = getattr(self.client, "interrupt", None)
        if not callable(interrupt):
            raise RuntimeError("Claude SDK client does not support interrupt()")
        result = interrupt()
        if inspect.isawaitable(result):
            await result
        self.interrupted = True


class ClaudeCodeRunner:
    """Run one Claude Code turn through the Claude Agent SDK."""

    def __init__(
        self,
        config: ClaudeCodeConfig,
        client_factory: ClientFactory | None = None,
        *,
        system_prompt_append: str = _RUNTIME_SYSTEM_PROMPT,
    ):
        self.config = config
        self.client_factory = client_factory or (lambda options: ClaudeSDKClient(options=options))
        self.event_adapter = ClaudeCodeEventAdapter()
        self.system_prompt_append = system_prompt_append

    def _options(self, record: ClaudeCodeChatRecord) -> ClaudeAgentOptions:
        system_prompt_append = (
            f"{self.system_prompt_append}\n"
            f"Current claudebot session_key: {record.chat_id}\n"
            "When creating schedules through agent_runtime, pass this exact session_key.\n"
        )
        return ClaudeAgentOptions(
            cwd=Path(record.workspace_path).expanduser(),
            env=self.config.to_env(),
            include_partial_messages=True,
            max_turns=self.config.max_turns,
            model=self.config.model,
            permission_mode=record.permission_mode.value,
            resume=record.claude_session_id or None,
            setting_sources=["project"],
            system_prompt={
                "type": "preset",
                "preset": "claude_code",
                "append": system_prompt_append,
            },
        )

    async def run_turn(
        self,
        record: ClaudeCodeChatRecord,
        prompt: str,
        on_event: Callable[[ClaudeCodeEvent], Any] | None = None,
        on_handle: Callable[[ClaudeCodeTurnHandle], Any] | None = None,
    ) -> ClaudeCodeRunResult:
        final_text = ""
        session_id = record.claude_session_id
        error_text = ""
        saw_turn_done = False
        client = self.client_factory(self._options(record))
        handle = ClaudeCodeTurnHandle(client)
        await self._emit(on_handle, handle)

        try:
            connect = getattr(client, "connect", None)
            if callable(connect):
                result = connect()
                if inspect.isawaitable(result):
                    await result
            await client.query(prompt, session_id=record.claude_session_id or "default")

            async for message in client.receive_response():
                for event in self._events_from_sdk_message(message):
                    if event.session_id:
                        session_id = event.session_id
                        record.claude_session_id = event.session_id
                    if event.kind == EventKind.TURN_DONE:
                        saw_turn_done = True
                        final_text = event.text
                    elif event.kind == EventKind.ERROR and event.text:
                        error_text = event.text
                    await self._emit(on_event, event)
        finally:
            disconnect = getattr(client, "disconnect", None)
            if callable(disconnect):
                result = disconnect()
                if inspect.isawaitable(result):
                    await result

        if handle.interrupted and error_text and not saw_turn_done:
            return ClaudeCodeRunResult(
                final_text="",
                session_id=session_id,
                exit_code=130,
            )
        if error_text and not saw_turn_done:
            raise RuntimeError(f"Claude Agent SDK returned an error: {error_text}")

        return ClaudeCodeRunResult(
            final_text=final_text,
            session_id=session_id,
            exit_code=130 if handle.interrupted else 0,
        )

    def _events_from_sdk_message(self, message: Any) -> list[ClaudeCodeEvent]:
        if isinstance(message, StreamEvent):
            return self.event_adapter.normalize_many(
                {
                    "type": "stream_event",
                    "session_id": message.session_id,
                    "event": message.event,
                }
            )
        if isinstance(message, AssistantMessage):
            return self._events_from_assistant(message)
        if isinstance(message, UserMessage):
            return self._events_from_user(message)
        if isinstance(message, ResultMessage):
            return self._events_from_result(message)
        if isinstance(message, SystemMessage):
            return self._events_from_system(message)
        return []

    def _events_from_assistant(self, message: AssistantMessage) -> list[ClaudeCodeEvent]:
        if message.error:
            return [
                ClaudeCodeEvent(
                    kind=EventKind.ERROR,
                    session_id=message.session_id or "",
                    text=message.error,
                    raw={"message": message},
                )
            ]

        events: list[ClaudeCodeEvent] = []
        for block in message.content:
            if isinstance(block, ThinkingBlock):
                events.append(
                    ClaudeCodeEvent(
                        kind=EventKind.THINKING_DELTA,
                        session_id=message.session_id or "",
                        text=block.thinking,
                        raw={"message": message, "block": block},
                    )
                )
            elif isinstance(block, (ToolUseBlock, ServerToolUseBlock)):
                events.append(
                    ClaudeCodeEvent(
                        kind=EventKind.TOOL_START,
                        session_id=message.session_id or "",
                        tool_use_id=block.id,
                        tool_name=block.name,
                        tool_input=block.input,
                        raw={"message": message, "block": block},
                    )
                )
        return events

    def _events_from_user(self, message: UserMessage) -> list[ClaudeCodeEvent]:
        content = message.content if isinstance(message.content, list) else []
        events: list[ClaudeCodeEvent] = []
        for block in content:
            if isinstance(block, (ToolResultBlock, ServerToolResultBlock)):
                events.append(
                    ClaudeCodeEvent(
                        kind=EventKind.TOOL_RESULT,
                        tool_use_id=block.tool_use_id,
                        text=self.event_adapter._content_text(block.content),
                        raw={"message": message, "block": block},
                    )
                )
        if message.tool_use_result:
            events.append(
                ClaudeCodeEvent(
                    kind=EventKind.TOOL_RESULT,
                    text=self.event_adapter._content_text(message.tool_use_result),
                    raw={"message": message},
                )
            )
        return events

    @staticmethod
    def _events_from_result(message: ResultMessage) -> list[ClaudeCodeEvent]:
        if message.is_error:
            text = "\n".join(message.errors or []) or message.result or "Claude Agent SDK error"
            return [
                ClaudeCodeEvent(
                    kind=EventKind.ERROR,
                    session_id=message.session_id,
                    text=text,
                    raw={"message": message},
                )
            ]
        return [
            ClaudeCodeEvent(
                kind=EventKind.TURN_DONE,
                session_id=message.session_id,
                text=message.result or "",
                raw={"message": message},
            )
        ]

    @staticmethod
    def _events_from_system(message: SystemMessage) -> list[ClaudeCodeEvent]:
        status = message.data.get("status")
        if not isinstance(status, str) or not status:
            return []
        return [
            ClaudeCodeEvent(
                kind=EventKind.STATUS,
                text=status,
                raw={"message": message},
            )
        ]

    @staticmethod
    async def _emit(
        on_event: Callable[[ClaudeCodeEvent], Any] | None, event: ClaudeCodeEvent
    ) -> None:
        if on_event is None:
            return
        result = on_event(event)
        if inspect.isawaitable(result):
            await result
