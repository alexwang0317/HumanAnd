from unittest.mock import MagicMock, patch

from src.services.github_monitor import check_pr, format_nudge, parse_github_map, poll_once, _seen_prs


GROUND_TRUTH = """# Project Ground Truth

## Core Objective
Launch the MVP by Friday with zero new database dependencies.

## Directory & Responsibilities
* **Alex** (<@U111>) — Database & Infrastructure. Owns schema design and migrations. github: alexwang0317
* **Sarah** (<@U222>) — Frontend & UI. Owns React components and design system. github: sarahdev

## AI Decision Log
"""


def test_parse_github_map_extracts_users():
    result = parse_github_map(GROUND_TRUTH)
    assert "alexwang0317" in result
    assert result["alexwang0317"]["name"] == "Alex"
    assert result["alexwang0317"]["slack_id"] == "U111"
    assert "Database & Infrastructure" in result["alexwang0317"]["role"]
    assert "sarahdev" in result
    assert result["sarahdev"]["name"] == "Sarah"


def test_parse_github_map_skips_entries_without_github():
    gt = "* **Dan** (<@U333>) — Product & Timelines.\n"
    result = parse_github_map(gt)
    assert len(result) == 0


def test_parse_github_map_case_insensitive():
    gt = "* **Alex** (<@U111>) — Backend. GitHub: AlexWang0317\n"
    result = parse_github_map(gt)
    assert "alexwang0317" in result


@patch("src.services.github_monitor.classify_pr")
@patch("src.services.github_monitor.fetch_pr_commits")
def test_check_pr_returns_none_for_unknown_author(mock_commits, mock_classify):
    agent = MagicMock()
    agent.ground_truth = GROUND_TRUTH
    pr = {"number": 1, "title": "Fix typo", "user": {"login": "unknown_user"}, "html_url": "https://github.com/pr/1"}

    result = check_pr(pr, "owner/repo", agent)
    assert result is None
    mock_classify.assert_not_called()


@patch("src.services.github_monitor.classify_pr", return_value="PASS")
@patch("src.services.github_monitor.fetch_pr_commits", return_value=["fix migration script"])
def test_check_pr_returns_none_on_pass(mock_commits, mock_classify):
    agent = MagicMock()
    agent.ground_truth = GROUND_TRUTH
    pr = {"number": 1, "title": "Fix migration", "user": {"login": "alexwang0317"}, "html_url": "https://github.com/pr/1"}

    result = check_pr(pr, "owner/repo", agent)
    assert result is None


@patch("src.services.github_monitor.classify_pr", return_value="NUDGE: Should this go to Sarah (Frontend & UI)?")
@patch("src.services.github_monitor.fetch_pr_commits", return_value=["redesign navbar component"])
def test_check_pr_returns_nudge(mock_commits, mock_classify):
    agent = MagicMock()
    agent.ground_truth = GROUND_TRUTH
    pr = {"number": 42, "title": "Redesign navbar", "user": {"login": "alexwang0317"}, "html_url": "https://github.com/pr/42"}

    result = check_pr(pr, "owner/repo", agent)
    assert result is not None
    assert result["pr_number"] == 42
    assert result["author_name"] == "Alex"
    assert "Sarah" in result["nudge_reason"]


def test_format_nudge_includes_pr_link_and_role():
    nudge = {
        "pr_number": 42,
        "pr_title": "Redesign navbar",
        "pr_url": "https://github.com/pr/42",
        "author_name": "Alex",
        "author_role": "Database & Infrastructure",
        "author_slack_id": "U111",
        "nudge_reason": "Should this go to Sarah?",
    }
    msg = format_nudge(nudge)
    assert "PR #42" in msg
    assert "https://github.com/pr/42" in msg
    assert "Database & Infrastructure" in msg
    assert "<@U111>" in msg


@patch("src.services.github_monitor._resolve_channel_id")
@patch("src.services.github_monitor.check_pr")
@patch("src.services.github_monitor.fetch_open_prs")
@patch("src.services.github_monitor.log_event")
def test_poll_once_skips_seen_prs(mock_log, mock_fetch, mock_check, mock_resolve):
    _seen_prs.add(99)
    mock_fetch.return_value = [{"number": 99, "title": "Old PR", "user": {"login": "alex"}, "html_url": "url"}]
    agents: dict = {}

    poll_once("owner/repo", MagicMock(), agents)
    mock_check.assert_not_called()
    _seen_prs.discard(99)


@patch("src.services.github_monitor._resolve_channel_id", return_value="C123")
@patch("src.services.github_monitor.check_pr")
@patch("src.services.github_monitor.fetch_open_prs")
@patch("src.services.github_monitor.log_event")
def test_poll_once_posts_nudge_to_slack(mock_log, mock_fetch, mock_check, mock_resolve):
    _seen_prs.clear()
    mock_fetch.return_value = [{"number": 50, "title": "New PR", "user": {"login": "alex"}, "html_url": "url"}]
    mock_check.return_value = {
        "pr_number": 50,
        "pr_title": "New PR",
        "pr_url": "url",
        "author_name": "Alex",
        "author_role": "Backend",
        "author_slack_id": "U111",
        "nudge_reason": "Mismatch",
    }
    slack_client = MagicMock()
    agents: dict = {"repo": MagicMock()}

    poll_once("owner/repo", slack_client, agents)
    slack_client.chat_postMessage.assert_called_once()
    call_kwargs = slack_client.chat_postMessage.call_args[1]
    assert call_kwargs["channel"] == "C123"
    _seen_prs.clear()
