from claudebot.claude_code.events import ClaudeCodeEventAdapter, EventKind


def test_text_delta_from_stream_event():
    adapter = ClaudeCodeEventAdapter()
    event = adapter.normalize(
        {
            "type": "stream_event",
            "event": {
                "type": "content_block_delta",
                "delta": {"type": "text_delta", "text": "hello"},
            },
            "session_id": "session-1",
        }
    )

    assert event is not None
    assert event.kind == EventKind.TEXT_DELTA
    assert event.text == "hello"
    assert event.session_id == "session-1"


def test_thinking_delta_from_stream_event():
    adapter = ClaudeCodeEventAdapter()
    event = adapter.normalize(
        {
            "type": "stream_event",
            "event": {
                "type": "content_block_delta",
                "delta": {"type": "thinking_delta", "thinking": "working"},
            },
            "session_id": "session-1",
        }
    )

    assert event is not None
    assert event.kind == EventKind.THINKING_DELTA
    assert event.text == "working"
    assert event.session_id == "session-1"


def test_tool_use_from_assistant_message():
    adapter = ClaudeCodeEventAdapter()
    events = adapter.normalize_many(
        {
            "type": "assistant",
            "session_id": "session-1",
            "message": {
                "content": [
                    {
                        "type": "tool_use",
                        "id": "tool-1",
                        "name": "Read",
                        "input": {"file_path": "x.py"},
                    },
                ],
            },
        }
    )

    assert len(events) == 1
    assert events[0].kind == EventKind.TOOL_START
    assert events[0].tool_name == "Read"
    assert events[0].tool_input == {"file_path": "x.py"}


def test_tool_result_from_user_message():
    adapter = ClaudeCodeEventAdapter()
    events = adapter.normalize_many(
        {
            "type": "user",
            "session_id": "session-1",
            "message": {
                "content": [
                    {"type": "tool_result", "tool_use_id": "tool-1", "content": "file content"},
                ],
            },
        }
    )

    assert len(events) == 1
    assert events[0].kind == EventKind.TOOL_RESULT
    assert events[0].tool_use_id == "tool-1"
    assert events[0].text == "file content"


def test_result_event():
    adapter = ClaudeCodeEventAdapter()
    event = adapter.normalize(
        {
            "type": "result",
            "subtype": "success",
            "result": "done",
            "session_id": "session-1",
        }
    )

    assert event is not None
    assert event.kind == EventKind.TURN_DONE
    assert event.text == "done"


def test_error_result_event_is_not_turn_done():
    adapter = ClaudeCodeEventAdapter()
    event = adapter.normalize(
        {
            "type": "result",
            "is_error": True,
            "result": "command failed",
            "session_id": "session-1",
        }
    )

    assert event is not None
    assert event.kind == EventKind.ERROR
    assert event.kind != EventKind.TURN_DONE
    assert event.text == "command failed"


def test_error_result_event_uses_error_status_fallback():
    adapter = ClaudeCodeEventAdapter()
    event = adapter.normalize(
        {
            "type": "result",
            "is_error": True,
            "api_error_status": 429,
            "session_id": "session-1",
        }
    )

    assert event is not None
    assert event.kind == EventKind.ERROR
    assert event.text == "429"


def test_system_hook_response_is_ignored():
    adapter = ClaudeCodeEventAdapter()

    assert (
        adapter.normalize(
            {
                "type": "system",
                "subtype": "hook_response",
                "status": "finished",
                "payload": {"large": ["data"]},
            }
        )
        is None
    )


def test_system_status_becomes_status_event():
    adapter = ClaudeCodeEventAdapter()
    event = adapter.normalize(
        {
            "type": "system",
            "subtype": "status",
            "status": "working",
            "session_id": "session-1",
        }
    )

    assert event is not None
    assert event.kind == EventKind.STATUS
    assert event.text == "working"


def test_tool_result_content_list_extracts_text_and_json_blocks():
    adapter = ClaudeCodeEventAdapter()
    events = adapter.normalize_many(
        {
            "type": "user",
            "message": {
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "tool-1",
                        "content": [
                            {"type": "text", "text": "first"},
                            {"text": "second"},
                            {"z": 2, "a": 1},
                        ],
                    },
                ],
            },
        }
    )

    assert len(events) == 1
    assert events[0].kind == EventKind.TOOL_RESULT
    assert events[0].text == 'first\nsecond\n{"a":1,"z":2}'


def test_tool_result_dict_content_extracts_text_or_stable_json():
    adapter = ClaudeCodeEventAdapter()
    text_event = adapter.normalize_many(
        {
            "type": "user",
            "message": {
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "tool-1",
                        "content": {"text": "plain text", "type": "text"},
                    },
                ],
            },
        }
    )[0]
    json_event = adapter.normalize_many(
        {
            "type": "user",
            "message": {
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "tool-2",
                        "content": {"z": 2, "a": 1},
                    },
                ],
            },
        }
    )[0]

    assert text_event.text == "plain text"
    assert json_event.text == '{"a":1,"z":2}'


def test_assistant_record_with_error_becomes_error():
    adapter = ClaudeCodeEventAdapter()
    events = adapter.normalize_many(
        {
            "type": "assistant",
            "session_id": "session-1",
            "error": {"message": "model failed", "code": "bad_request"},
        }
    )

    assert len(events) == 1
    assert events[0].kind == EventKind.ERROR
    assert events[0].text == '{"code":"bad_request","message":"model failed"}'


def test_ignored_unrelated_record():
    adapter = ClaudeCodeEventAdapter()

    assert adapter.normalize({"type": "unknown", "session_id": "session-1"}) is None
    assert adapter.normalize_many({"type": "unknown", "session_id": "session-1"}) == []
