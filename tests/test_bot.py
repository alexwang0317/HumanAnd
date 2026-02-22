import tempfile
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.handlers.slack_events import (
    _agents,
    _build_permalink,
    _check_text_approval,
    _format_diff,
    _get_agent,
    _parse_category,
    _pending_nudges,
    _pending_updates,
    handle_app_mention,
    handle_message,
    handle_reaction,
    register_handlers,
)
from src.stores.db import _connections, get_events, log_event


@contextmanager
def _project_env():
    """Real ProjectAgent + SQLite in a temp dir.

    Only mocks external boundaries: Slack API (resolve channel, fetch history),
    git subprocess. LLM calls must be patched per-test.
    """
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        with (
            patch("src.services.project_service.PROJECTS_DIR", tmp_path),
            patch("src.stores.db.PROJECTS_DIR", tmp_path),
            patch("src.services.project_service.subprocess.run"),
            patch("src.handlers.slack_events._resolve_channel_name", return_value="test-channel"),
            patch("src.handlers.slack_events.fetch_context", return_value=""),
        ):
            _agents.clear()
            _pending_updates.clear()
            _pending_nudges.clear()
            _connections.clear()
            yield tmp_path
            _agents.clear()
            _pending_updates.clear()
            _pending_nudges.clear()
            _connections.clear()


# --- Pure function tests (no mocks needed) ---


def test_register_handlers_adds_events():
    app = MagicMock()
    register_handlers(app)
    calls = [c[0][0] for c in app.event.call_args_list]
    assert "app_mention" in calls
    assert "message" in calls
    assert "reaction_added" in calls


def test_build_permalink():
    assert _build_permalink("C123", "123.456") == "https://slack.com/archives/C123/p123456"


def test_parse_category_with_category():
    result, cat = _parse_category("UPDATE|decision: Switch to Postgres")
    assert result == "UPDATE: Switch to Postgres"
    assert cat == "decision"


def test_parse_category_route():
    result, cat = _parse_category("ROUTE|escalation: <@U999> | needs DB help")
    assert result == "ROUTE: <@U999> | needs DB help"
    assert cat == "escalation"


def test_parse_category_without_category():
    result, cat = _parse_category("PASS")
    assert result == "PASS"
    assert cat == "general"


def test_format_diff_shows_context_and_addition():
    current = "## Core Objective\nLaunch MVP by Friday.\n\n## AI Decision Log\n(empty)"
    addition = "Team agreed to use PostgreSQL."
    result = _format_diff(current, addition)
    assert "+ Team agreed to use PostgreSQL." in result
    assert "(empty)" in result
    assert ":large_green_circle:" in result


def test_format_diff_with_short_content():
    current = "One line only."
    addition = "New entry."
    result = _format_diff(current, addition)
    assert "One line only." in result
    assert "+ New entry." in result


# --- Message handler tests ---


def test_handle_message_ignores_bot_messages():
    say = MagicMock()
    handle_message({"bot_id": "B123", "text": "hello"}, MagicMock(), say)
    say.assert_not_called()


def test_handle_message_ignores_subtypes():
    say = MagicMock()
    handle_message({"subtype": "channel_join", "text": "joined"}, MagicMock(), say)
    say.assert_not_called()


@patch("src.services.project_service.classify_message", return_value="PASS")
def test_handle_message_pass_stays_silent(_mock_llm):
    with _project_env():
        say = MagicMock()
        handle_message({"channel": "C123", "user": "U123", "text": "sounds good", "ts": "123.456"}, MagicMock(), say)
        say.assert_not_called()


@patch("src.services.project_service.classify_message", return_value="ROUTE|escalation: <@U999> | needs DB help")
def test_handle_message_route_tags_user(_mock_llm):
    with _project_env():
        say = MagicMock()
        handle_message({"channel": "C123", "user": "U123", "text": "who handles DB?", "ts": "123.456"}, MagicMock(), say)
        say.assert_called_once()
        msg = say.call_args[0][0]
        assert "<@U999>" in msg
        assert "<@U123>" in msg
        events = get_events("test-channel")
        assert events[0]["event_type"] == "ROUTE"


@patch("src.services.project_service.classify_message", return_value="UPDATE|decision: Switch to PostgreSQL")
def test_handle_message_update_proposes_change(_mock_llm):
    with _project_env():
        say = MagicMock()
        say.return_value = {"ts": "999.000"}
        handle_message({"channel": "C123", "user": "U123", "text": "let's use postgres", "ts": "123.456"}, MagicMock(), say)
        say.assert_called_once()
        msg = say.call_args[0][0]
        assert "+ Switch to PostgreSQL" in msg
        assert ":white_check_mark:" in msg
        assert "999.000" in _pending_updates
        pending = _pending_updates["999.000"]
        assert pending["category"] == "decision"
        assert pending["user"] == "U123"
        assert pending["permalink"] == "https://slack.com/archives/C123/p123456"
        events = get_events("test-channel")
        assert events[0]["event_type"] == "UPDATE"


@patch("src.services.project_service.classify_message", return_value="QUESTION|blocker: What do you mean by that?")
def test_handle_message_question_tracks_nudge(_mock_llm):
    with _project_env():
        say = MagicMock()
        say.return_value = {"ts": "777.000"}
        handle_message({"channel": "C123", "user": "U123", "text": "maybe change approach", "ts": "123.456"}, MagicMock(), say)
        say.assert_called_once()
        assert "777.000" in _pending_nudges
        assert _pending_nudges["777.000"]["nudge_text"] == "What do you mean by that?"
        assert _pending_nudges["777.000"]["user"] == "U123"
        events = get_events("test-channel")
        assert events[0]["event_type"] == "QUESTION"


@patch("src.services.project_service.classify_message", return_value="MISALIGN|pivot: The team agreed to use SQLite but this suggests MongoDB")
def test_handle_message_misalign_warns_and_tracks(_mock_llm):
    with _project_env():
        say = MagicMock()
        say.return_value = {"ts": "555.000"}
        handle_message({"channel": "C123", "user": "U123", "text": "let's switch to MongoDB", "ts": "123.456"}, MagicMock(), say)
        say.assert_called_once()
        msg = say.call_args[0][0]
        assert "MongoDB" in msg
        assert "555.000" in _pending_nudges
        events = get_events("test-channel")
        assert events[0]["event_type"] == "MISALIGN"


# --- Mention handler tests ---


@patch("src.services.project_service.respond_to_mention", return_value="The goal is to launch MVP by Friday.")
def test_handle_app_mention_responds(_mock_llm):
    with _project_env():
        say = MagicMock()
        handle_app_mention({"channel": "C123", "user": "U123", "text": "what's our goal?", "ts": "123.456"}, MagicMock(), say)
        say.assert_called_once_with("The goal is to launch MVP by Friday.", thread_ts="123.456")


def test_handle_app_mention_role_command():
    with _project_env():
        agent = _get_agent("test-channel")
        agent.initialize([{"id": "U123", "real_name": "Alex", "name": "alex", "title": ""}])

        say = MagicMock()
        handle_app_mention({"channel": "C123", "user": "U123", "text": "<@BOT123> role Database & Infrastructure", "ts": "123.456"}, MagicMock(), say)
        say.assert_called_once()
        assert "Database & Infrastructure" in say.call_args[0][0]
        assert "Database & Infrastructure" in agent.ground_truth


# --- Reaction handler tests ---


def test_reaction_approve_updates_ground_truth():
    with _project_env():
        event_id = log_event("test-channel", "UPDATE", "U123", "decision", "Switch to PostgreSQL", "https://slack.com/archives/C123/p123456")
        _pending_updates["999.000"] = {
            "update_text": "Switch to PostgreSQL",
            "channel_name": "test-channel",
            "channel_id": "C123",
            "thread_ts": "123.456",
            "category": "decision",
            "user": "U123",
            "permalink": "https://slack.com/archives/C123/p123456",
            "event_id": event_id,
        }
        client = MagicMock()
        client.conversations_members.return_value = {"members": ["U123"]}
        handle_reaction({"reaction": "white_check_mark", "user": "U456", "item": {"ts": "999.000", "channel": "C123"}}, client, MagicMock())
        assert "999.000" not in _pending_updates
        assert "Switch to PostgreSQL" in _agents["test-channel"].ground_truth
        events = get_events("test-channel")
        assert events[0]["reaction"] == "approved"
        assert events[0]["reacted_by"] == "U456"


def test_reaction_reject_discards_change():
    with _project_env():
        event_id = log_event("test-channel", "UPDATE", "U123", "decision", "Switch to PostgreSQL", "https://slack.com/archives/C123/p888000")
        _pending_updates["888.000"] = {
            "update_text": "Switch to PostgreSQL",
            "channel_name": "test-channel",
            "channel_id": "C123",
            "thread_ts": "123.456",
            "category": "decision",
            "user": "U123",
            "permalink": "https://slack.com/archives/C123/p888000",
            "event_id": event_id,
        }
        handle_reaction({"reaction": "x", "user": "U456", "item": {"ts": "888.000", "channel": "C123"}}, MagicMock(), MagicMock())
        assert "888.000" not in _pending_updates
        events = get_events("test-channel")
        assert events[0]["reaction"] == "rejected"


def test_reaction_approve_nudge():
    with _project_env():
        event_id = log_event("test-channel", "QUESTION", "U123", "blocker", "What do you mean?", "https://slack.com/archives/C123/p777000")
        _pending_nudges["777.000"] = {
            "nudge_text": "What do you mean by that?",
            "channel_name": "test-channel",
            "thread_ts": "123.456",
            "user": "U123",
            "event_id": event_id,
        }
        client = MagicMock()
        handle_reaction({"reaction": "white_check_mark", "user": "U456", "item": {"ts": "777.000", "channel": "C123"}}, client, MagicMock())
        assert "777.000" not in _pending_nudges
        assert "off-track" in client.chat_postMessage.call_args[1]["text"]
        events = get_events("test-channel")
        assert events[0]["reaction"] == "approved"


def test_reaction_dismiss_nudge():
    with _project_env():
        event_id = log_event("test-channel", "QUESTION", "U123", "blocker", "Are you sure?", "https://slack.com/archives/C123/p666000")
        _pending_nudges["666.000"] = {
            "nudge_text": "Are you sure about that?",
            "channel_name": "test-channel",
            "thread_ts": "123.456",
            "user": "U123",
            "event_id": event_id,
        }
        client = MagicMock()
        handle_reaction({"reaction": "x", "user": "U456", "item": {"ts": "666.000", "channel": "C123"}}, client, MagicMock())
        assert "666.000" not in _pending_nudges
        assert "on track" in client.chat_postMessage.call_args[1]["text"]
        events = get_events("test-channel")
        assert events[0]["reaction"] == "rejected"


# --- Text approval tests ---


def test_text_approval_accepts_update():
    with _project_env():
        event_id = log_event("test-channel", "UPDATE", "U123", "decision", "Switch to PostgreSQL", "https://slack.com/archives/C123/p111000")
        _pending_updates["111.000"] = {
            "update_text": "Switch to PostgreSQL",
            "channel_name": "test-channel",
            "channel_id": "C123",
            "thread_ts": "111.000",
            "category": "decision",
            "user": "U123",
            "permalink": "https://slack.com/archives/C123/p111000",
            "event_id": event_id,
        }
        client = MagicMock()
        result = _check_text_approval({"channel": "C123", "user": "U456", "text": "yes", "thread_ts": "111.000"}, client, MagicMock())
        assert result is True
        assert "111.000" not in _pending_updates
        assert "updated" in client.chat_postMessage.call_args[1]["text"].lower()
        assert "Switch to PostgreSQL" in _agents["test-channel"].ground_truth


def test_text_rejection_discards_update():
    with _project_env():
        event_id = log_event("test-channel", "UPDATE", "U123", "decision", "Switch to PostgreSQL", "https://slack.com/archives/C123/p222000")
        _pending_updates["222.000"] = {
            "update_text": "Switch to PostgreSQL",
            "channel_name": "test-channel",
            "channel_id": "C123",
            "thread_ts": "222.000",
            "category": "decision",
            "user": "U123",
            "permalink": "https://slack.com/archives/C123/p222000",
            "event_id": event_id,
        }
        client = MagicMock()
        result = _check_text_approval({"channel": "C123", "user": "U456", "text": "no", "thread_ts": "222.000"}, client, MagicMock())
        assert result is True
        assert "222.000" not in _pending_updates
        assert "discarded" in client.chat_postMessage.call_args[1]["text"].lower()
        events = get_events("test-channel")
        assert events[0]["reaction"] == "rejected"


def test_text_approval_case_insensitive():
    with _project_env():
        for i, word in enumerate(["Yes", "YES", "y", "Y", "Yeah"]):
            ts = f"{333 + i}.000"
            event_id = log_event("test-channel", "UPDATE", "U123", "decision", "Add caching", "link")
            _pending_updates[ts] = {
                "update_text": "Add caching",
                "channel_name": "test-channel",
                "channel_id": "C123",
                "thread_ts": ts,
                "category": "decision",
                "user": "U123",
                "permalink": "link",
                "event_id": event_id,
            }
            result = _check_text_approval({"channel": "C123", "user": "U456", "text": word, "thread_ts": ts}, MagicMock(), MagicMock())
            assert result is True, f"Failed for word: {word}"
            assert ts not in _pending_updates
