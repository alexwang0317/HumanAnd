"""Integration test — requires real Slack tokens in .env and network access."""

import os

import pytest
from dotenv import load_dotenv
from slack_sdk import WebClient

load_dotenv()

BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN", "")
SLACK_TEST_CHANNEL = os.environ.get("SLACK_TEST_CHANNEL", "")


@pytest.fixture
def client():
    if not BOT_TOKEN:
        pytest.skip("SLACK_BOT_TOKEN not set")
    return WebClient(token=BOT_TOKEN)


def test_bot_can_authenticate(client):
    response = client.auth_test()
    assert response["ok"]
    print(f"Authenticated as: {response['user']}")


def test_bot_can_post_message(client):
    if not SLACK_TEST_CHANNEL:
        pytest.skip("SLACK_TEST_CHANNEL not set")

    response = client.chat_postMessage(
        channel=SLACK_TEST_CHANNEL,
        text="HumanAnd test message — if you see this, the bot is working.",
    )
    assert response["ok"]
    print(f"Posted test message to {SLACK_TEST_CHANNEL}")
