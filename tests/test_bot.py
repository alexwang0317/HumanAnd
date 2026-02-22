from unittest.mock import MagicMock, patch

from src.handlers.slack_events import (
    _build_permalink,
    _check_text_approval,
    _format_diff,
    _parse_category,
    _pending_nudges,
    _pending_updates,
    handle_app_mention,
    handle_message,
    handle_reaction,
    register_handlers,
)


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


def test_handle_message_ignores_bot_messages():
    event = {"bot_id": "B123", "text": "hello"}
    say = MagicMock()
    client = MagicMock()
    handle_message(event, client, say)
    say.assert_not_called()


def test_handle_message_ignores_subtypes():
    event = {"subtype": "channel_join", "text": "joined"}
    say = MagicMock()
    client = MagicMock()
    handle_message(event, client, say)
    say.assert_not_called()


@patch("src.handlers.slack_events.fetch_context", return_value="")
@patch("src.handlers.slack_events._get_agent")
@patch("src.handlers.slack_events._resolve_channel_name", return_value="test_channel")
def test_handle_message_pass_stays_silent(mock_resolve, mock_agent, mock_history):
    mock_agent.return_value.classify.return_value = "PASS"
    event = {"channel": "C123", "user": "U123", "text": "sounds good", "ts": "123.456"}
    say = MagicMock()
    client = MagicMock()
    handle_message(event, client, say)
    say.assert_not_called()


@patch("src.handlers.slack_events.log_event", return_value=1)
@patch("src.handlers.slack_events.fetch_context", return_value="")
@patch("src.handlers.slack_events._get_agent")
@patch("src.handlers.slack_events._resolve_channel_name", return_value="test_channel")
def test_handle_message_route_tags_user(mock_resolve, mock_agent, mock_history, mock_db):
    mock_agent.return_value.classify.return_value = "ROUTE|escalation: <@U999> | needs DB help"
    event = {"channel": "C123", "user": "U123", "text": "who handles DB?", "ts": "123.456"}
    say = MagicMock()
    client = MagicMock()
    handle_message(event, client, say)
    say.assert_called_once()
    msg = say.call_args[0][0]
    assert "<@U999>" in msg
    assert "<@U123>" in msg
    mock_agent.return_value.log_message.assert_called_once()


@patch("src.handlers.slack_events.log_event", return_value=42)
@patch("src.handlers.slack_events.fetch_context", return_value="")
@patch("src.handlers.slack_events._get_agent")
@patch("src.handlers.slack_events._resolve_channel_name", return_value="test_channel")
def test_handle_message_update_proposes_change(mock_resolve, mock_agent, mock_history, mock_db):
    mock_agent.return_value.classify.return_value = "UPDATE|decision: Switch to PostgreSQL"
    mock_agent.return_value.ground_truth = "## Core Objective\nLaunch MVP by Friday."
    event = {"channel": "C123", "user": "U123", "text": "let's use postgres", "ts": "123.456"}
    say = MagicMock()
    say.return_value = {"ts": "999.000"}
    client = MagicMock()
    handle_message(event, client, say)
    say.assert_called_once()
    msg = say.call_args[0][0]
    assert "+ Switch to PostgreSQL" in msg
    assert ":white_check_mark:" in msg
    assert "999.000" in _pending_updates
    pending = _pending_updates["999.000"]
    assert pending["category"] == "decision"
    assert pending["user"] == "U123"
    assert pending["permalink"] == "https://slack.com/archives/C123/p123456"
    assert pending["event_id"] == 42
    del _pending_updates["999.000"]


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


@patch("src.handlers.slack_events.update_reaction")
@patch("src.handlers.slack_events._get_agent")
@patch("src.handlers.slack_events._resolve_channel_name", return_value="test_channel")
def test_reaction_approve_updates_ground_truth(mock_resolve, mock_agent, mock_db_react):
    _pending_updates["999.000"] = {
        "update_text": "Switch to PostgreSQL",
        "channel_name": "test_channel",
        "channel_id": "C123",
        "thread_ts": "123.456",
        "category": "decision",
        "user": "U123",
        "permalink": "https://slack.com/archives/C123/p123456",
        "event_id": 42,
    }
    mock_agent.return_value.validate_directory.return_value = []
    event = {
        "reaction": "white_check_mark",
        "user": "U123",
        "item": {"ts": "999.000", "channel": "C123"},
    }
    client = MagicMock()
    client.conversations_members.return_value = {"members": ["U123"]}
    say = MagicMock()
    handle_reaction(event, client, say)
    mock_agent.return_value.apply_update.assert_called_once_with("Switch to PostgreSQL", "U123")
    mock_agent.return_value.log_message.assert_called_once()
    assert "999.000" not in _pending_updates


@patch("src.handlers.slack_events.update_reaction")
@patch("src.handlers.slack_events._get_agent")
@patch("src.handlers.slack_events._resolve_channel_name", return_value="test_channel")
def test_reaction_reject_discards_change(mock_resolve, mock_agent, mock_db_react):
    _pending_updates["888.000"] = {
        "update_text": "Switch to PostgreSQL",
        "channel_name": "test_channel",
        "channel_id": "C123",
        "thread_ts": "123.456",
        "category": "decision",
        "user": "U123",
        "permalink": "https://slack.com/archives/C123/p888000",
        "event_id": 43,
    }
    event = {
        "reaction": "x",
        "user": "U123",
        "item": {"ts": "888.000", "channel": "C123"},
    }
    client = MagicMock()
    say = MagicMock()
    handle_reaction(event, client, say)
    mock_agent.return_value.apply_update.assert_not_called()
    assert "888.000" not in _pending_updates


@patch("src.handlers.slack_events.log_event", return_value=10)
@patch("src.handlers.slack_events.fetch_context", return_value="")
@patch("src.handlers.slack_events.Path")
@patch("src.handlers.slack_events._get_agent")
@patch("src.handlers.slack_events._resolve_channel_name", return_value="test_channel")
def test_handle_message_question_tracks_nudge(mock_resolve, mock_agent, mock_path, mock_history, mock_db):
    mock_agent.return_value.classify.return_value = "QUESTION|blocker: What do you mean by that?"
    mock_path.return_value.read_text.return_value = "Hey, just checking — {nudge_content} Does that still align with what we agreed on?\n"
    event = {"channel": "C123", "user": "U123", "text": "maybe change approach", "ts": "123.456"}
    say = MagicMock()
    say.return_value = {"ts": "777.000"}
    client = MagicMock()
    handle_message(event, client, say)
    say.assert_called_once()
    mock_agent.return_value.log_message.assert_called_once()
    assert "777.000" in _pending_nudges
    assert _pending_nudges["777.000"]["nudge_text"] == "What do you mean by that?"
    assert _pending_nudges["777.000"]["user"] == "U123"
    del _pending_nudges["777.000"]


@patch("src.handlers.slack_events.fetch_context", return_value="")
@patch("src.handlers.slack_events._get_agent")
@patch("src.handlers.slack_events._resolve_channel_name", return_value="test_channel")
def test_handle_app_mention_responds(mock_resolve, mock_agent, mock_history):
    mock_agent.return_value.respond.return_value = "The goal is to launch MVP by Friday."
    event = {"channel": "C123", "user": "U123", "text": "what's our goal?", "ts": "123.456"}
    say = MagicMock()
    client = MagicMock()
    handle_app_mention(event, client, say)
    say.assert_called_once_with("The goal is to launch MVP by Friday.", thread_ts="123.456")


@patch("src.handlers.slack_events._get_agent")
@patch("src.handlers.slack_events._resolve_channel_name", return_value="test_channel")
def test_handle_app_mention_role_command(mock_resolve, mock_agent):
    mock_agent.return_value.set_role.return_value = "Updated your role: Database & Infrastructure"
    event = {"channel": "C123", "user": "U123", "text": "<@BOT123> role Database & Infrastructure", "ts": "123.456"}
    say = MagicMock()
    client = MagicMock()
    handle_app_mention(event, client, say)
    mock_agent.return_value.set_role.assert_called_once_with("U123", "Database & Infrastructure")
    say.assert_called_once()


@patch("src.handlers.slack_events.update_reaction")
def test_reaction_approve_nudge(mock_db_react):
    _pending_nudges["777.000"] = {
        "nudge_text": "What do you mean by that?",
        "channel_name": "test_channel",
        "thread_ts": "123.456",
        "user": "U123",
        "event_id": 10,
    }
    event = {
        "reaction": "white_check_mark",
        "user": "U456",
        "item": {"ts": "777.000", "channel": "C123"},
    }
    client = MagicMock()
    say = MagicMock()
    handle_reaction(event, client, say)
    assert "777.000" not in _pending_nudges
    client.chat_postMessage.assert_called_once()
    msg = client.chat_postMessage.call_args[1]["text"]
    assert "off-track" in msg


@patch("src.handlers.slack_events.update_reaction")
def test_reaction_dismiss_nudge(mock_db_react):
    _pending_nudges["666.000"] = {
        "nudge_text": "Are you sure about that?",
        "channel_name": "test_channel",
        "thread_ts": "123.456",
        "user": "U123",
        "event_id": 11,
    }
    event = {
        "reaction": "x",
        "user": "U456",
        "item": {"ts": "666.000", "channel": "C123"},
    }
    client = MagicMock()
    say = MagicMock()
    handle_reaction(event, client, say)
    assert "666.000" not in _pending_nudges
    client.chat_postMessage.assert_called_once()
    msg = client.chat_postMessage.call_args[1]["text"]
    assert "on track" in msg


@patch("src.handlers.slack_events.update_reaction")
@patch("src.handlers.slack_events._get_agent")
def test_text_approval_accepts_update(mock_agent, mock_db_react):
    mock_agent.return_value.apply_update.return_value = False
    _pending_updates["111.000"] = {
        "update_text": "Switch to PostgreSQL",
        "channel_name": "test_channel",
        "channel_id": "C123",
        "thread_ts": "111.000",
        "category": "decision",
        "user": "U123",
        "permalink": "https://slack.com/archives/C123/p111000",
        "event_id": 50,
    }
    event = {"channel": "C123", "user": "U456", "text": "yes", "thread_ts": "111.000"}
    client = MagicMock()
    say = MagicMock()
    result = _check_text_approval(event, client, say)
    assert result is True
    assert "111.000" not in _pending_updates
    mock_agent.return_value.apply_update.assert_called_once_with("Switch to PostgreSQL", "U456")
    client.chat_postMessage.assert_called_once()
    assert "updated" in client.chat_postMessage.call_args[1]["text"].lower()


@patch("src.handlers.slack_events.update_reaction")
@patch("src.handlers.slack_events._get_agent")
def test_text_rejection_discards_update(mock_agent, mock_db_react):
    _pending_updates["222.000"] = {
        "update_text": "Switch to PostgreSQL",
        "channel_name": "test_channel",
        "channel_id": "C123",
        "thread_ts": "222.000",
        "category": "decision",
        "user": "U123",
        "permalink": "https://slack.com/archives/C123/p222000",
        "event_id": 51,
    }
    event = {"channel": "C123", "user": "U456", "text": "no", "thread_ts": "222.000"}
    client = MagicMock()
    say = MagicMock()
    result = _check_text_approval(event, client, say)
    assert result is True
    assert "222.000" not in _pending_updates
    mock_agent.return_value.apply_update.assert_not_called()
    assert "discarded" in client.chat_postMessage.call_args[1]["text"].lower()


@patch("src.handlers.slack_events.update_reaction")
@patch("src.handlers.slack_events._get_agent")
def test_text_approval_case_insensitive(mock_agent, mock_db_react):
    for word in ["Yes", "YES", "y", "Y", "Yeah"]:
        _pending_updates["333.000"] = {
            "update_text": "Add caching",
            "channel_name": "test_channel",
            "channel_id": "C123",
            "thread_ts": "333.000",
            "category": "decision",
            "user": "U123",
            "permalink": "https://slack.com/archives/C123/p333000",
            "event_id": 52,
        }
        event = {"channel": "C123", "user": "U456", "text": word, "thread_ts": "333.000"}
        client = MagicMock()
        say = MagicMock()
        result = _check_text_approval(event, client, say)
        assert result is True, f"Failed for word: {word}"
        assert "333.000" not in _pending_updates


@patch("src.handlers.slack_events.log_event", return_value=20)
@patch("src.handlers.slack_events.fetch_context", return_value="")
@patch("src.handlers.slack_events.Path")
@patch("src.handlers.slack_events._get_agent")
@patch("src.handlers.slack_events._resolve_channel_name", return_value="test_channel")
def test_handle_message_misalign_warns_and_tracks(mock_resolve, mock_agent, mock_path, mock_history, mock_db):
    mock_agent.return_value.classify.return_value = "MISALIGN|pivot: The team agreed to use SQLite but this suggests MongoDB"
    mock_path.return_value.read_text.return_value = ":warning: Heads up — {misalign_content} This seems to conflict with what's in the ground truth.\n"
    event = {"channel": "C123", "user": "U123", "text": "let's switch to MongoDB", "ts": "123.456"}
    say = MagicMock()
    say.return_value = {"ts": "555.000"}
    client = MagicMock()
    handle_message(event, client, say)
    say.assert_called_once()
    msg = say.call_args[0][0]
    assert ":warning:" in msg
    assert "conflict" in msg
    mock_agent.return_value.log_message.assert_called_once()
    assert "555.000" in _pending_nudges
    assert "MongoDB" in _pending_nudges["555.000"]["nudge_text"]
    del _pending_nudges["555.000"]
