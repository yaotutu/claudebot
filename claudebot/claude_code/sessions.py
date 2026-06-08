"""Claude Code chat metadata persistence."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any

from claudebot.claude_code.config import PermissionMode

_SAFE_KEY_RE = re.compile(r"[^A-Za-z0-9_.:-]+")
_SAFE_KEY_PREFIX_LENGTH = 120
_SAFE_KEY_HASH_LENGTH = 16


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(slots=True)
class ClaudeCodeChatRecord:
    chat_id: str
    workspace_path: str
    permission_mode: PermissionMode
    claude_session_id: str = ""
    title: str = ""
    preview: str = ""
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)
    transcript: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ClaudeCodeChatRecord":
        return cls(
            chat_id=str(data["chat_id"]),
            workspace_path=str(data.get("workspace_path") or ""),
            permission_mode=PermissionMode(data.get("permission_mode") or PermissionMode.FULL),
            claude_session_id=str(data.get("claude_session_id") or ""),
            title=str(data.get("title") or ""),
            preview=str(data.get("preview") or ""),
            created_at=str(data.get("created_at") or _now()),
            updated_at=str(data.get("updated_at") or _now()),
            transcript=list(data.get("transcript") or []),
        )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["permission_mode"] = self.permission_mode.value
        return data


class ClaudeCodeSessionStore:
    def __init__(self, root: Path):
        self.root = root
        self.sessions_dir = root / "claude-code-sessions"
        self.sessions_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def safe_key(chat_id: str) -> str:
        prefix = _SAFE_KEY_RE.sub("_", chat_id)[:_SAFE_KEY_PREFIX_LENGTH] or "chat"
        digest = sha256(chat_id.encode("utf-8")).hexdigest()[:_SAFE_KEY_HASH_LENGTH]
        return f"{prefix}-{digest}"

    def path_for(self, chat_id: str) -> Path:
        return self.sessions_dir / f"{self.safe_key(chat_id)}.json"

    def get(self, chat_id: str) -> ClaudeCodeChatRecord | None:
        path = self.path_for(chat_id)
        if not path.exists():
            return None
        return ClaudeCodeChatRecord.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def get_or_create(
        self,
        chat_id: str,
        *,
        workspace_path: str,
        permission_mode: PermissionMode,
    ) -> ClaudeCodeChatRecord:
        existing = self.get(chat_id)
        if existing is not None:
            return existing
        return ClaudeCodeChatRecord(
            chat_id=chat_id,
            workspace_path=workspace_path,
            permission_mode=permission_mode,
        )

    def save(self, record: ClaudeCodeChatRecord) -> None:
        record.updated_at = _now()
        path = self.path_for(record.chat_id)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(record.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)

    def delete(self, chat_id: str) -> bool:
        path = self.path_for(chat_id)
        if not path.exists():
            return False
        path.unlink()
        return True

    def list(self) -> list[ClaudeCodeChatRecord]:
        records = []
        for path in self.sessions_dir.glob("*.json"):
            record = ClaudeCodeChatRecord.from_dict(json.loads(path.read_text(encoding="utf-8")))
            records.append((record, path.stat().st_mtime_ns))
        return [
            record
            for record, _mtime_ns in sorted(
                records,
                key=lambda item: (item[0].updated_at, item[1]),
                reverse=True,
            )
        ]
