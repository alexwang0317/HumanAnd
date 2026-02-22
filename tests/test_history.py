from unittest.mock import MagicMock

from src.utils.history import fetch_context


def test_formats_messages_oldest_first():
    client = MagicMock()
    client.conversations_history.return_value = {
        "messages": [
            {"user": "U222", "text": "second message"},
            {"user": "U111", "text": "first message"},
        ]
    }
    result = fetch_context(client, "C123")
    lines = result.strip().splitlines()
    assert lines[0] == "<@U111>: first message"
    assert lines[1] == "<@U222>: second message"


def test_skips_bot_messages():
    client = MagicMock()
    client.conversations_history.return_value = {
        "messages": [
            {"user": "U111", "text": "human message"},
            {"bot_id": "B999", "text": "bot message"},
        ]
    }
    result = fetch_context(client, "C123")
    assert "human message" in result
    assert "bot message" not in result


def test_skips_subtypes():
    client = MagicMock()
    client.conversations_history.return_value = {
        "messages": [
            {"subtype": "channel_join", "text": "joined"},
            {"user": "U111", "text": "real message"},
        ]
    }
    result = fetch_context(client, "C123")
    assert "joined" not in result
    assert "real message" in result


def test_empty_channel():
    client = MagicMock()
    client.conversations_history.return_value = {"messages": []}
    result = fetch_context(client, "C123")
    assert result == ""
