"""Minimal WebUI turn state for the Claude Code gateway."""

from __future__ import annotations

import time
from typing import Any

from claudebot.bus.events import OutboundMessage

WEBUI_SESSION_METADATA_KEY = "webui"

# Wall-clock turn start per ``chat_id`` (websocket only). Survives browser refresh while the
# gateway process stays up; cleared on idle/stop and implicitly dropped on restart.
_WEBSOCKET_TURN_WALL_STARTED_AT: dict[str, float] = {}


def websocket_turn_wall_started_at(chat_id: str) -> float | None:
    """Return the active turn start timestamp for a WebSocket chat, if any."""
    return _WEBSOCKET_TURN_WALL_STARTED_AT.get(chat_id)


def mark_webui_session(metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return metadata marked as originating from the WebUI."""
    merged = dict(metadata or {})
    merged[WEBUI_SESSION_METADATA_KEY] = True
    return merged


async def publish_turn_run_status(
    bus: Any,
    msg: Any,
    status: str,
    *,
    started_at: float | None = None,
) -> None:
    """Publish lightweight WebUI turn run status and track running wall-clock time."""
    if getattr(msg, "channel", None) != "websocket":
        return

    chat_id = str(getattr(msg, "chat_id", ""))
    metadata = mark_webui_session({"event": "turn_run_status", "status": status})
    if status == "running":
        t0 = started_at if started_at is not None else time.time()
        _WEBSOCKET_TURN_WALL_STARTED_AT[chat_id] = t0
        metadata["started_at"] = t0
    else:
        _WEBSOCKET_TURN_WALL_STARTED_AT.pop(chat_id, None)

    await bus.publish_outbound(
        OutboundMessage(
            channel="websocket",
            chat_id=chat_id,
            content="",
            metadata=metadata,
        )
    )
