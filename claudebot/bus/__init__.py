"""Message bus module for decoupled channel-agent communication."""

from claudebot.bus.events import InboundMessage, OutboundMessage
from claudebot.bus.queue import MessageBus

__all__ = ["MessageBus", "InboundMessage", "OutboundMessage"]
