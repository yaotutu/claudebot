from pathlib import Path

from claudebot.claude_code.config import PermissionMode
from claudebot.claude_code.sessions import ClaudeCodeSessionStore


def test_create_update_reload_chat_record(tmp_path: Path):
    store = ClaudeCodeSessionStore(tmp_path)

    record = store.get_or_create(
        chat_id="chat-1",
        workspace_path="/tmp/project",
        permission_mode=PermissionMode.FULL,
    )
    record.claude_session_id = "11111111-1111-4111-8111-111111111111"
    record.title = "Project work"
    record.preview = "hello"
    store.save(record)

    reloaded = ClaudeCodeSessionStore(tmp_path).get("chat-1")

    assert reloaded is not None
    assert reloaded.chat_id == "chat-1"
    assert reloaded.workspace_path == "/tmp/project"
    assert reloaded.permission_mode == PermissionMode.FULL
    assert reloaded.claude_session_id == "11111111-1111-4111-8111-111111111111"
    assert reloaded.title == "Project work"
    assert reloaded.preview == "hello"


def test_list_sessions_sorted_by_updated_at(tmp_path: Path):
    store = ClaudeCodeSessionStore(tmp_path)
    first = store.get_or_create("a", workspace_path="/tmp/a", permission_mode=PermissionMode.FULL)
    second = store.get_or_create("b", workspace_path="/tmp/b", permission_mode=PermissionMode.EDIT)
    store.save(first)
    store.save(second)

    records = store.list()

    assert [r.chat_id for r in records] == ["b", "a"]


def test_sanitized_chat_id_collisions_are_stored_separately(tmp_path: Path):
    store = ClaudeCodeSessionStore(tmp_path)
    slash_record = store.get_or_create(
        "a/b",
        workspace_path="/tmp/slash",
        permission_mode=PermissionMode.FULL,
    )
    question_record = store.get_or_create(
        "a?b",
        workspace_path="/tmp/question",
        permission_mode=PermissionMode.EDIT,
    )

    store.save(slash_record)
    store.save(question_record)

    assert store.path_for("a/b") != store.path_for("a?b")
    assert store.get("a/b").workspace_path == "/tmp/slash"
    assert store.get("a?b").workspace_path == "/tmp/question"


def test_long_chat_ids_with_same_truncated_prefix_get_different_paths(tmp_path: Path):
    store = ClaudeCodeSessionStore(tmp_path)
    first_chat_id = f"{'a' * 200}-first"
    second_chat_id = f"{'a' * 200}-second"

    assert store.path_for(first_chat_id) != store.path_for(second_chat_id)
