"""Claude Code stream event normalization."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class EventKind(str, Enum):
    TEXT_DELTA = "text_delta"
    THINKING_DELTA = "thinking_delta"
    TOOL_START = "tool_start"
    TOOL_RESULT = "tool_result"
    ERROR = "error"
    TURN_DONE = "turn_done"
    STATUS = "status"


@dataclass(slots=True)
class ClaudeCodeEvent:
    kind: EventKind
    session_id: str = ""
    text: str = ""
    tool_use_id: str = ""
    tool_name: str = ""
    tool_input: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)


class ClaudeCodeEventAdapter:
    def normalize(self, record: dict[str, Any]) -> ClaudeCodeEvent | None:
        events = self.normalize_many(record)
        if not events:
            return None
        return events[0]

    def normalize_many(self, record: dict[str, Any]) -> list[ClaudeCodeEvent]:
        record_type = record.get("type")
        if record_type == "stream_event":
            return self._normalize_stream_event(record)
        if record_type == "assistant":
            return self._normalize_assistant(record)
        if record_type == "user":
            return self._normalize_user(record)
        if record_type == "result":
            if record.get("is_error") is True:
                return [self._event(EventKind.ERROR, record, text=self._result_error_text(record))]
            return [
                self._event(
                    EventKind.TURN_DONE, record, text=self._content_text(record.get("result"))
                )
            ]
        if record_type == "system":
            text = self._system_text(record)
            if text:
                return [self._event(EventKind.STATUS, record, text=text)]
            return []
        if record_type == "error":
            return [
                self._event(EventKind.ERROR, record, text=self._content_text(record.get("error")))
            ]
        return []

    def _normalize_stream_event(self, record: dict[str, Any]) -> list[ClaudeCodeEvent]:
        event = record.get("event")
        if not isinstance(event, dict) or event.get("type") != "content_block_delta":
            return []

        delta = event.get("delta")
        if not isinstance(delta, dict):
            return []

        delta_type = delta.get("type")
        if delta_type == "text_delta":
            return [self._event(EventKind.TEXT_DELTA, record, text=self._text(delta.get("text")))]
        if delta_type == "thinking_delta":
            text = delta.get("thinking", delta.get("text"))
            return [self._event(EventKind.THINKING_DELTA, record, text=self._text(text))]
        return []

    def _normalize_assistant(self, record: dict[str, Any]) -> list[ClaudeCodeEvent]:
        if "error" in record:
            return [
                self._event(EventKind.ERROR, record, text=self._content_text(record.get("error")))
            ]

        events = []
        for item in self._message_content(record):
            if item.get("type") != "tool_use":
                continue
            tool_input = item.get("input")
            events.append(
                self._event(
                    EventKind.TOOL_START,
                    record,
                    tool_use_id=self._text(item.get("id")),
                    tool_name=self._text(item.get("name")),
                    tool_input=tool_input if isinstance(tool_input, dict) else {},
                )
            )
        return events

    def _normalize_user(self, record: dict[str, Any]) -> list[ClaudeCodeEvent]:
        events = []
        for item in self._message_content(record):
            if item.get("type") != "tool_result":
                continue
            events.append(
                self._event(
                    EventKind.TOOL_RESULT,
                    record,
                    text=self._content_text(item.get("content")),
                    tool_use_id=self._text(item.get("tool_use_id")),
                )
            )
        return events

    def _event(
        self,
        kind: EventKind,
        record: dict[str, Any],
        *,
        text: str = "",
        tool_use_id: str = "",
        tool_name: str = "",
        tool_input: dict[str, Any] | None = None,
    ) -> ClaudeCodeEvent:
        return ClaudeCodeEvent(
            kind=kind,
            session_id=self._text(record.get("session_id")),
            text=text,
            tool_use_id=tool_use_id,
            tool_name=tool_name,
            tool_input=tool_input or {},
            raw=record,
        )

    @staticmethod
    def _message_content(record: dict[str, Any]) -> list[dict[str, Any]]:
        message = record.get("message")
        if not isinstance(message, dict):
            return []
        content = message.get("content")
        if not isinstance(content, list):
            return []
        return [item for item in content if isinstance(item, dict)]

    @staticmethod
    def _system_text(record: dict[str, Any]) -> str:
        if record.get("subtype") != "status":
            return ""

        status = record.get("status")
        if not isinstance(status, str) or len(status) > 200:
            return ""
        return status

    @staticmethod
    def _result_error_text(record: dict[str, Any]) -> str:
        for key in ("result", "error", "api_error_status"):
            text = ClaudeCodeEventAdapter._content_text(record.get(key))
            if text:
                return text
        return "Claude Code returned an error"

    @staticmethod
    def _content_text(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        if isinstance(value, list):
            parts = []
            for item in value:
                if isinstance(item, dict) and "text" in item:
                    parts.append(ClaudeCodeEventAdapter._content_text(item.get("text")))
                elif isinstance(item, (dict, list)):
                    parts.append(ClaudeCodeEventAdapter._json_text(item))
                else:
                    parts.append(ClaudeCodeEventAdapter._text(item))
            return "\n".join(part for part in parts if part)
        if isinstance(value, dict):
            if "text" in value:
                return ClaudeCodeEventAdapter._content_text(value.get("text"))
            return ClaudeCodeEventAdapter._json_text(value)
        return ClaudeCodeEventAdapter._text(value)

    @staticmethod
    def _json_text(value: Any) -> str:
        try:
            return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        except (TypeError, ValueError):
            return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)

    @staticmethod
    def _text(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        return str(value)
