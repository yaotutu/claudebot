"""Compatibility exports for WebUI-attached MCP preset annotations."""

from __future__ import annotations

from typing import Any


def runtime_lines(_value: Any) -> list[str]:
    return []


def session_extra(_value: Any) -> dict[str, Any]:
    return {}


__all__ = ["runtime_lines", "session_extra"]
