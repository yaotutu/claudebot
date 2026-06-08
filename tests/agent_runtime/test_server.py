import json

from claudebot.agent_runtime import server


def test_agent_runtime_schedule_tools_write_workspace_store(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDEBOT_WORKSPACE", str(tmp_path))

    created = server.add_schedule(
        name="Morning check",
        message="Check project status",
        session_key="websocket:abc",
        kind="every",
        every_seconds=3600,
    )

    job = created["job"]
    assert job["name"] == "Morning check"
    assert job["schedule"]["every_ms"] == 3_600_000
    assert job["payload"]["session_key"] == "websocket:abc"

    payload = server.list_schedules(session_key="websocket:abc")
    assert [row["id"] for row in payload["jobs"]] == [job["id"]]

    store = json.loads((tmp_path / ".claude" / "agent" / "schedules.json").read_text())
    assert store["jobs"][0]["payload"]["message"] == "Check project status"

    disabled = server.set_schedule_enabled(job["id"], False)
    assert disabled["status"] == "updated"
    assert disabled["job"]["enabled"] is False

    removed = server.remove_schedule(job["id"])
    assert removed == {"status": "removed"}
