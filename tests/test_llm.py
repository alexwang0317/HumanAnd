from unittest.mock import MagicMock, patch

from llm import classify_message, respond_to_mention


def _mock_response(text: str) -> MagicMock:
    block = MagicMock()
    block.text = text
    response = MagicMock()
    response.content = [block]
    return response


@patch("llm._get_client")
@patch("llm._load_prompt")
def test_classify_returns_pass(mock_prompt, mock_client):
    mock_prompt.return_value = "system prompt {ground_truth} {user} {message}"
    mock_client.return_value.messages.create.return_value = _mock_response("PASS")

    result = classify_message("Launch MVP by Friday", "U123", "sounds good")
    assert result == "PASS"


@patch("llm._get_client")
@patch("llm._load_prompt")
def test_classify_returns_route(mock_prompt, mock_client):
    mock_prompt.return_value = "system prompt {ground_truth} {user} {message}"
    mock_client.return_value.messages.create.return_value = _mock_response(
        "ROUTE: <@U999> | needs help with database"
    )

    result = classify_message("Launch MVP", "U123", "who handles the DB?")
    assert result.startswith("ROUTE:")
    assert "<@U999>" in result


@patch("llm._get_client")
@patch("llm._load_prompt")
def test_classify_returns_update(mock_prompt, mock_client):
    mock_prompt.return_value = "system prompt {ground_truth} {user} {message}"
    mock_client.return_value.messages.create.return_value = _mock_response(
        "UPDATE: Team decided to switch to PostgreSQL"
    )

    result = classify_message("Launch MVP", "U123", "let's go with postgres")
    assert result.startswith("UPDATE:")


@patch("llm._get_client")
@patch("llm._load_prompt")
def test_classify_returns_question(mock_prompt, mock_client):
    mock_prompt.return_value = "system prompt {ground_truth} {user} {message}"
    mock_client.return_value.messages.create.return_value = _mock_response(
        "QUESTION: What exactly do you mean by 'change the approach'?"
    )

    result = classify_message("Launch MVP", "U123", "maybe we should change the approach")
    assert result.startswith("QUESTION:")


@patch("llm._get_client")
@patch("llm._load_prompt")
def test_classify_returns_misalign(mock_prompt, mock_client):
    mock_prompt.return_value = "system prompt {ground_truth} {user} {message}"
    mock_client.return_value.messages.create.return_value = _mock_response(
        "MISALIGN: conflicts with ground truth — team agreed on SQLite"
    )

    result = classify_message("Use SQLite for storage", "U123", "let's switch to MongoDB")
    assert result.startswith("MISALIGN:")
    assert "SQLite" in result


@patch("llm._get_client")
@patch("llm._load_prompt")
def test_respond_to_mention(mock_prompt, mock_client):
    mock_prompt.return_value = "system prompt {ground_truth}"
    mock_client.return_value.messages.create.return_value = _mock_response(
        "The team's goal is to launch the MVP by Friday."
    )

    result = respond_to_mention("Launch MVP by Friday", "what's our goal?")
    assert "MVP" in result
