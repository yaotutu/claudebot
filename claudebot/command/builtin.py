"""Built-in slash command metadata for the Claude Code gateway."""

from __future__ import annotations

import asyncio
import os
import sys
from dataclasses import dataclass

from claudebot.bus.events import OutboundMessage
from claudebot.command.router import CommandContext, CommandRouter
from claudebot.utils.restart import set_restart_notice_to_env


@dataclass(frozen=True)
class BuiltinCommandSpec:
    command: str
    title: str
    description: str
    icon: str
    arg_hint: str = ""

    def as_dict(self) -> dict[str, str]:
        return {
            "command": self.command,
            "title": self.title,
            "description": self.description,
            "icon": self.icon,
            "arg_hint": self.arg_hint,
        }


BUILTIN_COMMAND_SPECS: tuple[BuiltinCommandSpec, ...] = (
    BuiltinCommandSpec(
        "/stop",
        "Stop current task",
        "Cancel the active Claude Code turn for this chat.",
        "square",
    ),
    BuiltinCommandSpec(
        "/restart",
        "Restart claudebot",
        "Restart the gateway process in place.",
        "rotate-cw",
    ),
    BuiltinCommandSpec(
        "/help",
        "Show help",
        "List available slash commands.",
        "circle-help",
    ),
)


def builtin_command_palette() -> list[dict[str, str]]:
    """Return structured command metadata for UI command palettes."""
    return [spec.as_dict() for spec in BUILTIN_COMMAND_SPECS]


async def cmd_restart(ctx: CommandContext) -> OutboundMessage:
    """Restart the process in-place via os.execv."""
    msg = ctx.msg
    set_restart_notice_to_env(
        channel=msg.channel,
        chat_id=msg.chat_id,
        metadata=dict(msg.metadata or {}),
    )

    async def _do_restart() -> None:
        await asyncio.sleep(1)
        os.execv(sys.executable, [sys.executable, "-m", "claudebot"] + sys.argv[1:])

    asyncio.create_task(_do_restart())
    return OutboundMessage(
        channel=msg.channel,
        chat_id=msg.chat_id,
        content="Restarting...",
        metadata=dict(msg.metadata or {}),
    )


async def cmd_help(ctx: CommandContext) -> OutboundMessage:
    """Return the built-in command help text."""
    return OutboundMessage(
        channel=ctx.msg.channel,
        chat_id=ctx.msg.chat_id,
        content=build_help_text(),
        metadata={**dict(ctx.msg.metadata or {}), "render_as": "text"},
    )


def build_help_text() -> str:
    """Build canonical help text shared across channels."""
    lines = ["claudebot commands:"]
    for spec in BUILTIN_COMMAND_SPECS:
        command = spec.command
        if spec.arg_hint:
            command = f"{command} {spec.arg_hint}"
        lines.append(f"{command} - {spec.description}")
    return "\n".join(lines)


def register_builtin_commands(router: CommandRouter) -> None:
    """Register gateway-compatible slash commands."""
    router.priority("/restart", cmd_restart)
    router.exact("/help", cmd_help)
